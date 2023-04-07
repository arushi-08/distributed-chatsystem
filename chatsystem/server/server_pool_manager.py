import json
import threading
from time import sleep
import grpc
import chat_system_pb2
import chat_system_pb2_grpc
import server.constants as C
from server.storage.file_manager import FileManager
from server.storage.utils import get_timestamp
from queue import Queue


class ThreadSafeDict:
    def __init__(self, initial={}):
        self._lock = threading.Lock()
        self._state = initial

    def __setitem__(self, key, value):
        with self._lock:
            self._state[key] = value

    def __getitem__(self, key):
        with self._lock:
            return self._state[key]

    def __contains__(self, key):
        return (key in self._state)

    def __str__(self) -> str:
        return self._state.__str__()

    def get(self, key):
        return self._state.get(key)
    
    def get_dict(self):
        return self._state
    
    def values(self):
        with self._lock:
            return self._state.values()


def join_server(server_string, server_id):
    try:
        # print(f"Trying to connect to server: {server_string}")
        channel = grpc.insecure_channel(server_string)
        stub = chat_system_pb2_grpc.ChatServerStub(channel)
        server_status = stub.Ping(chat_system_pb2.PingMessage(server_id=server_id))
        if server_status.status is True:
            print(f"Connected to server: {server_string}")
            return stub
            # sleep(C.CONNECT_SERVER_INTERVAL)
    except Exception as e:
        # print("exception: ", e)
        pass

class ServerPoolManager:
    def __init__(self, id, file_manager: FileManager) -> None:
        """
        id: id of current server
        """
        self.id = id
        self.file_manager = file_manager
        self.num_servers = 5
        self.active_stubs = {}
        self.thread_events = {}
        self.message_queues = {}
        self.delete_timestamp_queue = Queue()
        self.message_timestamp_lock = threading.Lock()
        self.queue_timestamp_dict = ThreadSafeDict()
        self.create_message_queues()
        self.load_queue_messages_from_disk()
        self.connect_to_servers()
        
    

    def keep_alive_sync(self, server_id):
        """
        triggered for each server
        joins server
        waits for message events
        when there is new message -> reads message queue -> sends message to connected servers
        when connection drops (2nd server crash), it removes stub and checks for new connection 
        """
        try:
            while True:
                if C.USE_DIFFERENT_PORTS:
                    server_string = f'localhost:{(11999+server_id)}'
                else:
                    server_string = C.SERVER_STRING.format(server_id)
                stub = join_server(server_string, self.id)
                if stub:
                    # connected to server
                    self.active_stubs[server_id] = stub
                    message_queue = self.message_queues[server_id]
                    message_event = self.thread_events[server_id]

                    while True:
                        while message_queue.qsize():
                            queue_message = message_queue.queue[0]
                            timestamp, message = queue_message
                            
                            server_message = chat_system_pb2.ServerMessage(
                                group_id=message.get('group_id'),
                                user_id=message.get('user_id'),
                                creation_time=message.get('creation_time'),
                                text=message.get('text'),
                                message_id=message.get('message_id'),
                                likes=message.get('likes'),
                                message_type=message.get('message_type'),
                                vector_timestamp =message.get('vector_timestamp'),
                                event_type=message.get('event_type'),
                                users=message.get('users')
                            )
                            try:
                                status = stub.SyncMessagetoServer(server_message)
                                if status.status:
                                    message_queue.get(0)
                                    self.queue_timestamp_dict[server_id] = timestamp
                                    print("here 1")
                                    if timestamp:
                                        self.file_manager.fast_write(f"{server_id}_last_sent_timestamp", json.dumps(timestamp).encode('utf-8'))

                            except grpc.RpcError as er:
                                del self.active_stubs[server_id]
                                stub = None
                                break
                            except Exception as e:
                                print(e)
                                break
                        if stub is None:
                            # if stub is None, don't wait for new messages
                            break
                        message_event.wait()
                        message_event.clear()


                sleep(C.CONNECT_SERVER_INTERVAL)
        finally:
            if server_id in self.active_stubs:
                del self.active_stubs[server_id]
        pass

    def send_msg_to_recovered_servers(self, recovered_server_id):
        self.thread_events[recovered_server_id].set()
        pass

    def connect_to_servers(self):
        id = self.id
        num_servers = self.num_servers
        active_stubs = self.active_stubs
        # while len(active_stubs) < num_servers-1:
        for i in range(1, num_servers + 1):
            try:
                if id == i or active_stubs.get(i) is not None: 
                    continue
                t = threading.Thread(target=self.keep_alive_sync, 
                                     daemon=True, 
                                     args=[i])
                t.start()
            except Exception:
                pass
        try:
            t = threading.Thread(target=self.delete_queue_messages,
                                 daemon=True)
            t.start()
        except Exception as e:
            print(f'Error in thread delete_queue_messages: {e}')
        
    
    def get_connected_servers_view(self):
        return sorted(self.active_stubs.keys())
    
    def get_unique_timestamp(self):
        with self.message_timestamp_lock:
            return get_timestamp()
        
    def delete_queue_messages(self):
        while True:
            min_timestamp = min(self.queue_timestamp_dict.values())
            while self.delete_timestamp_queue.qsize():
                timestamp = self.delete_timestamp_queue.queue[0]
                if min_timestamp >= timestamp:
                    self.file_manager.delete_file(str(timestamp), fast=True)
                    self.delete_timestamp_queue.get(0)
                else:
                    break
            sleep(C.DELETE_MESSAGE_FROM_DISK_INTERVAL)

    def create_message_queues(self):
        for i in range(1, self.num_servers + 1):
            if self.id == i:
                continue
            self.thread_events[i] = threading.Event()
            self.message_queues[i] = Queue()
            self.queue_timestamp_dict[i] = 0
            
    def load_queue_messages_from_disk(self):
        queue_msg_files = self.file_manager.list_files(fast=True)
        queue_msg_files.sort()

        for file in queue_msg_files:
            if file.endswith('_last_sent_timestamp'):
                print("FILE", file)
                lines = self.file_manager.fast_read(file)
                print("lines",lines)
                last_sent_timestamp = json.loads(lines)
                server_id = int(file.split("_")[0])
                self.queue_timestamp_dict[server_id] = last_sent_timestamp

        for file in queue_msg_files:
            if not file.endswith('_last_sent_timestamp'):
                timestamp = int(file)
                self.delete_timestamp_queue.put(timestamp)
                message = json.loads(self.file_manager.fast_read(file))
                queue_object = (timestamp, message)
                for i in range(1, self.num_servers + 1):
                    if self.id == i or self.queue_timestamp_dict[i] >= timestamp: 
                        continue
                    self.message_queues[i].put(queue_object)
                    # self.thread_events[i].set()
                self.delete_timestamp_queue.put(timestamp)

    def send_msg_to_connected_servers(self, message, event_type=C.MESSAGE_EVENT):
        timestamp = self.get_unique_timestamp()
        message['event_type'] = event_type
        queue_object = (timestamp, message)
        for i in range(1, self.num_servers + 1):
            # try:
            if self.id == i: 
                continue
            self.message_queues[i].put(queue_object)
            self.thread_events[i].set()
        self.delete_timestamp_queue.put(timestamp)
        file_name = str(timestamp)
        print("here 2")
        self.file_manager.fast_write(file_name, json.dumps(message).encode('utf-8'))
