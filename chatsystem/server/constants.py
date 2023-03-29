
import os

STORE_DATA_ON_FILE_SYSTEM = True

DATA_STORE_FILE_DIR_PATH = os.path.join(os.path.expanduser('~'), 'data', 'chat_server')

os.makedirs(DATA_STORE_FILE_DIR_PATH, exist_ok=True)

DATA_STORE_FILE_PATH = os.path.join(DATA_STORE_FILE_DIR_PATH, 'server_datastore.json')

CONNECTION_COMMANDS = ['c']
LOGIN_COMMANDS = ['u']
JOIN_GROUP_COMMANDS = ['j']
EXIT_APP_COMMANDS = ['q']
APPEND_TO_CHAT_COMMANDS = ['a']
LIKE_COMMANDS = ['l']
UNLIKE_COMMANDS = ['r']
NEW = 'new'
USER_JOIN = 'joined'
USER_LEFT = 'left'

MESSAGE_UPDATE_INTERVAL = 50

CONNECT_SERVER_INTERVAL = 10

USE_DIFFERENT_PORTS = os.getenv('USE_DIFFERENT_PORTS', '1') == '1'

SERVER_STRING = '172.30.100.10{}:12000'