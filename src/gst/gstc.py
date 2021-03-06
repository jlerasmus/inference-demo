import json
import logging
import socket
import subprocess
import psutil
import time

GSTD_PROCNAME = 'gstd'
terminator = '\x00'.encode('utf-8')
max_size = 8192
def recvall(sock):
    buf = b''
    count = max_size
    try:
        while count:
            newbuf = sock.recv(max_size//8)
            if not newbuf: return None
            if terminator in newbuf:
                # this is the last item
                buf += newbuf[:newbuf.find(terminator)]
                break
            else:
                buf += newbuf
                count -= len(newbuf)
    except socket.error:
        buf = json.dumps({"error":"socket error", "msg": traceback.format_exc(), "code": -1 })
    return buf

# Add color to logging output
COLORS = {
    'WARNING': '33m',
    'INFO': '37m',
    'DEBUG': '34m',
    'CRITICAL': '35m',
    'ERROR': '31m'
}
class colorFormatter(logging.Formatter):
    def __init__(self, msg):
        logging.Formatter.__init__(self, msg)

    def format(self, record):
        if record.levelname in COLORS:
            record.levelname = "\033[1;" + COLORS[record.levelname] + record.levelname + "\033[0m"
        return logging.Formatter.format(self, record)

class client(object):
    def __init__(self, ip='localhost', port=5000, logfile=None, loglevel='ERROR'):
        
        # Init the logger
        self.logger = logging.getLogger('GSTD')
        self.logger.setLevel(logging.DEBUG)
        # Select to log in a file or console
        if logfile:
            # log in file
            log = logging.FileHandler(logfile)
        else:
            # log in console
            log = logging.StreamHandler()
        # Set log format with colors
        log.setFormatter(colorFormatter("%(asctime)22s  %(levelname)s    \t%(message)s"))
        # Set log level
        numeric_level = getattr(logging, loglevel.upper(), None)
        if isinstance(numeric_level, int):
            log.setLevel(numeric_level)
        else:
            log.setLevel(logging.ERROR)
        self.logger.addHandler(log)

        self.ip = ip
        self.port = port
        self.proc = None
        self.pipes = []
        self.gstd_started = False
        self.logger.info('Starting GSTD instance with ip=%s port=%d logfile=%s loglevel=%s', self.ip, self.port, logfile, loglevel)
        self.test_gstd()

    def __del__(self):
        self.logger.info('Destroying GSTD instance with ip=%s port=%d', self.ip, self.port)
        self.logger.info('Deleting pipelines...')
        while (self.pipes != []):
            ret = self.pipeline_delete(self.pipes[0])
            if (ret != 0):
                self.pipes.pop(0)
        if (self.gstd_started):
            self.logger.info('Killing GStreamer Daemon process...')
            self.proc.kill()

    def socket_send(self, line):
        self.logger.debug('GSTD socket sending line: %s', line)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((self.ip, self.port))
            s.send(' '.join(line).encode('utf-8'))
            data = recvall(s)
            data = data.decode('utf-8')
        except socket.error:
            self.logger.error('GSTD socket error')
            data = None
        self.logger.debug('GSTD socket received answer:\n %s', data)
        return data

    def start_gstd(self):
        try:
            gstd_bin = subprocess.check_output(['which',GSTD_PROCNAME])
            gstd_bin = gstd_bin.rstrip()
            self.logger.info('Startting GStreamer Daemon...')
            subprocess.Popen([gstd_bin])
            time.sleep(3)
            if self.test_gstd():
                self.gstd_started = True
                self.logger.info("GStreamer Daemon started successfully!")
                return True
            else:
                self.logger.info("GStreamer Daemon did not start correctly...")
                return False
        except subprocess.CalledProcessError:
            # Did not find gstd
            self.logger.error("GStreamer Daemon is not running and it is not installed.")
            self.logger.error("To get GStreamer Daemon, visit https://www.ridgerun.com/gstd.")
        return False

    def test_gstd(self):
        if self.ip not in ['localhost', '127.0.0.1']:
            # bypass process check, we don't know how to start gstd remotely
            self.logger.warning("Assuming GSTD is running in the remote host at %s" % self.ip )
            return True
        for proc in psutil.process_iter():
        # check whether the process name matches
            if proc.name() == GSTD_PROCNAME:
                self.proc = proc
        if self.proc or self.start_gstd():
            # we already had gstd or were able to start it.
            return True
        else:
            self.logger.error("GStreamer Daemon is not running and couldn't be started")
            return False

    def create(self, uri, property, value):
        self.logger.info('Creating property %s in uri %s with value "%s"', property, uri, value)
        cmd_line = ['create', uri, property, value]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] == 0 and uri == "pipelines"):
                self.pipes.append(property)
            else:
                self.logger.error('Uri create error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('URI create error')
            traceback.print_exc()
            return None

    def read(self, uri):
        self.logger.info('Reading uri %s', uri)
        cmd_line = ['read', uri]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            return result
        except Exception:
            self.logger.error('URI read error')
            traceback.print_exc()
            return None

    def update(self, uri, value):
        self.logger.info('Updating uri %s with value "%s"', uri, value)
        cmd_line = ['update', uri, value]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Uri update error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('URI update error')
            traceback.print_exc()
            return None

    def delete(self, uri, name):
        self.logger.info('Deleting name %s at uri "%s"', name, uri)
        cmd_line = ['delete', uri, name]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] == 0 and uri == "pipelines"):
                self.pipes.remove(name)
            else:
                self.logger.error('Uri delete error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('URI delete error')
            traceback.print_exc()
            return None

    def pipeline_create(self, pipe_name,  pipe_desc):
        self.logger.info('Creating pipeline %s with description "%s"', pipe_name, pipe_desc)
        cmd_line = ['pipeline_create', pipe_name, pipe_desc]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] == 0):
                self.pipes.append(pipe_name)
            else:
                self.logger.error('Pipeline create error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('Pipeline create error')
            traceback.print_exc()
            return None

    def pipeline_delete(self, pipe_name):
        self.logger.info('Deleting pipeline %s', pipe_name)
        cmd_line = ['pipeline_delete', pipe_name]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] == 0):
                self.pipes.remove(pipe_name)
            else:
                self.logger.error('Pipeline delete error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('Pipeline delete error')
            traceback.print_exc()
            return None

    def pipeline_play(self, pipe_name):
        self.logger.info('Playing pipeline %s', pipe_name)
        cmd_line = ['pipeline_play', pipe_name]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Pipeline play error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('Pipeline play error')
            traceback.print_exc()
            return None

    def pipeline_pause(self, pipe_name):
        self.logger.info('Pausing pipeline %s', pipe_name)
        cmd_line = ['pipeline_pause', pipe_name]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Pipeline pause error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('Pipeline pause error')
            traceback.print_exc()
            return None

    def pipeline_stop(self, pipe_name):
        self.logger.info('Stoping pipeline %s', pipe_name)
        cmd_line = ['pipeline_stop', pipe_name]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Pipeline stop error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('Pipeline stop error')
            traceback.print_exc()
            return None

    def element_set(self, pipe_name, element, prop, value):
        self.logger.info('Setting element %s %s property in pipeline %s to:%s', element, prop, pipe_name, value)
        cmd_line = ['element_set', pipe_name, "%s %s %s" % (element, prop, value) ]
        jresult = self.socket_send(cmd_line)
        try:
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Element set error: %s', result['description'])
        except KeyError:
            self.logger.warning("The data did not contain a valid response")
        except TypeError:
            self.logger.warning("Socket result is not buf/str")
        return result['code']

    def gstd_element_get(self, pipe_name, element, prop):
        self.logger.info('Getting value of element %s %s property in pipeline %s', element, prop, pipe_name)
        cmd_line = ['element_get', pipe_name, "%s %s" % (element, prop) ]
        jresult = self.socket_send(cmd_line)
        try:
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Element get error: %s', result['description'])
            value = result['response']['value']
        except KeyError:
            self.logger.warning("The data did not contain a valid response")
            value = None
        except TypeError:
            self.logger.warning("Socket result is not buf/str")
            value = None
        if value==None:
            self.logger.error("invalid value received")
        return value

    def list_pipelines(self):
        self.logger.info('Listing pipelines')
        cmd_line = ['list_pipelines']
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Pipelines list error: %s', result['description'])
            return result['nodes']
        except Exception:
            self.logger.error('Pipelines list error')
            traceback.print_exc()
            return None

    def list_elements(self, pipe):
        self.logger.info('Listing elements of pipeline %s', pipe)
        cmd_line = ['list_elements', pipe]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Elements list error: %s', result['description'])
            return result['nodes']
        except Exception:
            self.logger.error('Elements list error')
            traceback.print_exc()
            return None

    def list_properties(self, pipe, element):
        self.logger.info('Listing properties of  element %s from pipeline %s', element, pipeline)
        cmd_line = ['list_properties', pipe, element]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Properties list error: %s', result['description'])
            return result['nodes']
        except Exception:
            self.logger.error('Properties list error')
            traceback.print_exc()
            return None

    def list_signals(self, pipe, element):
        self.logger.info('Listing signals of  element %s from pipeline %s', element, pipeline)
        cmd_line = ['list_signals', pipe, element]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Signals list error: %s', result['description'])
            return result['nodes']
        except Exception:
            self.logger.error('Signals list error')
            traceback.print_exc()
            return None

    def bus_read(self, pipe):
        self.logger.info('Reading bus of pipeline %s', pipe)
        cmd_line = ['bus_read', pipe]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
        except Exception:
            self.logger.error('Bus read error')
            traceback.print_exc()
            return None

    def bus_filter(self, pipe, filter):
        self.logger.info('Reading bus of pipeline %s with filter %s', pipe, filter)
        cmd_line = ['bus_filter', pipe, filter]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            return result
        except Exception:
            self.logger.error('Bus read error')
            traceback.print_exc()
            return None

    def bus_timeout(self, pipe, timeout):
        self.logger.info('Reading bus of pipeline %s with timeout %s', pipe, timeout)
        cmd_line = ['bus_timeout', pipe, timeout]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            return result
        except Exception:
            self.logger.error('Timeout set error')
            traceback.print_exc()
            return None

    def event_eos(self, pipe):
        self.logger.info('Sending end-of-stream event to pipeline %s', pipe)
        cmd_line = ['event_eos', pipe]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('End-of-stream event error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('End-of-stream event error')
            traceback.print_exc()
            return None

    def event_seek (self, pipe, rate=1.0, format=3, flags=1, start_type=1, start=0, end_type=1, end=-1):
        self.logger.info('Performing event seek in pipeline %s', pipe)
        cmd_line = ['event_seek', pipe, rate, format, flags, start_type, start, end_type, end]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Event seek error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('Event seek error')
            traceback.print_exc()
            return None

    def event_flush_start(self, pipe):
        self.logger.info('Putting pipeline %s in flushing mode', pipe)
        cmd_line = ['event_flush_start', pipe]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Event flush start error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('Event flush start error')
            traceback.print_exc()
            return None

    def event_flush_stop(self, pipe, reset=True):
        self.logger.info('Taking pipeline %s out of flushing mode', pipe)
        cmd_line = ['event_flush_stop', pipe]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Event flush stop error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('Event flush stop error')
            traceback.print_exc()
            return None

    def signal_connect(self, pipe, element, signal):
        self.logger.info('Connecting to signal %s of element %s from pipeline %s', signal, element, pipe)
        cmd_line = ['signal_connect', pipe, element, signal]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            return result
        except Exception:
            self.logger.error('Signal connect error')
            traceback.print_exc()
            return None

    def signal_timeout(self, pipe, element, signal, timeout):
        self.logger.info('Connecting to signal %s of element %s from pipeline %s with timeout %s', signal, element, pipe, timeout)
        cmd_line = ['signal_timeout', pipe, element, signal, timeout]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            return result
        except Exception:
            self.logger.error('Signal connect error')
            traceback.print_exc()
            return None

    def signal_disconnect(self, pipe, element, signal):
        self.logger.info('Disonnecting from signal %s of element %s from pipeline %s', signal, element, pipe)
        cmd_line = ['signal_disconnect', pipe, element, signal]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            return result
        except Exception:
            self.logger.error('Signal disconnect error')
            traceback.print_exc()
            return None

    def debug_enable(self, enable):
        self.logger.info('Enabling/Disabling GStreamer debug')
        cmd_line = ['debug_enable', enable]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Debug enable error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('Debug enable error')
            traceback.print_exc()
            return None

    def debug_threshold(self, threshold):
        self.logger.info('Setting GStreamer debug threshold to %s', threshold)
        cmd_line = ['debug_threshold', threshold]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Debug threshold error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('Debug threshold error')
            traceback.print_exc()
            return None

    def debug_color(self, colors):
        self.logger.info('Enabling/Disabling GStreamer debug colors')
        cmd_line = ['debug_color', color]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Debug colors error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('Debug color error')
            traceback.print_exc()
            return None

    def debug_reset(self, reset):
        self.logger.info('Enabling/Disabling GStreamer debug threshold reset')
        cmd_line = ['debug_reset', reset]
        try:
            jresult = self.socket_send(cmd_line)
            result = json.loads(jresult)
            if (result['code'] != 0):
                self.logger.error('Debug reset error: %s', result['description'])
            return result['code']
        except Exception:
            self.logger.error('Debug reset error')
            traceback.print_exc()
            return None
