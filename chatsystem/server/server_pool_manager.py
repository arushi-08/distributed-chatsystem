import threading
from time import sleep
import grpc
import chat_system_pb2
import chat_system_pb2_grpc
import server.constants as C
from queue import Queue


class ServerState:
    def __init__(self, initial={}):
        self._lock = threading.Lock()
        self._state = initial

    def __setitem__(self, key, value):
        with self._lock:
            self._state[key] = value

    def __getitem__(self, key):
        return self._state[key]

    def __contains__(self, key):
        return (key in self._state)

    def __str__(self) -> str:
        return self._state.__str__()

    def get(self, key):
        return self._state.get(key)
    
    def get_dict(self):
        return self._state


def join_server(server_string):
    try:
        # print(f"Trying to connect to server: {server_string}")
        channel = grpc.insecure_channel(server_string)
        stub = chat_system_pb2_grpc.ChatServerStub(channel)
        server_status = stub.Ping(chat_system_pb2.BlankMessage())
        if server_status.status is True:
            print(f"Connected to server: {server_string}")
            return stub
            # sleep(C.CONNECT_SERVER_INTERVAL)
    except:
        pass

class ServerPoolManager:
    def __init__(self, id, file_manager) -> None:
        """
        id: id of current server
        """
        self.id = id
        self.file_manager = file_manager
        self.num_servers = 5
        self.active_stubs = {}
        self.thread_events = {}
        self.message_queues = {}
        self.connect_to_servers()
    

    def keep_alive_sync(self, server_id):
        try:
            while True:
                if C.USE_DIFFERENT_PORTS:
                    server_string = f'localhost:{(11999+server_id)}'
                else:
                    server_string = C.SERVER_STRING.format(server_id)
                stub = join_server(server_string)
                if stub:
                    self.active_stubs[server_id] = stub
                    message_queue = self.message_queues[server_id]
                    message_event = self.thread_events[server_id]
                    while True:
                        while message_queue.qsize():
                            message = message_queue.queue[0]
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
                                stub.SyncMessagetoServer(server_message)
                                message_queue.get(0)
                            except:
                                pass

                        message_event.wait()
                        message_event.clear()


                sleep(C.CONNECT_SERVER_INTERVAL)
        finally:
            if server_id in self.active_stubs:
                del self.active_stubs[server_id]
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
                self.thread_events[i] = threading.Event()
                self.message_queues[i] = Queue()
                t = threading.Thread(target=self.keep_alive_sync, 
                            daemon=True, 
                            args=[i])
                t.start()
            except Exception:
                pass
    
    def get_connected_servers_view(self):
        return sorted(self.active_stubs.keys())

    def send_msg_to_connected_servers(self, message, event_type=C.MESSAGE_EVENT):

        message['event_type'] = event_type
        
        pass

