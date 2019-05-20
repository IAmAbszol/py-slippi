import io
import sys

import slippi.event as evt
import slippi.game as gm

from slippi.util import *

from threading import Lock, Thread

class LiveGame(Base):
    """ Read live data from an on-going game of Super Smash Brothers Melee. """

    def __init__(self):
        self.frames = []
        self._out_of_order = False
        self.stream_ptr = None
        self.game = gm.Game()
        self.thread = None
        self.kill = False
        self.mutex = Lock()

    def _read_stream(self, path):
        """
        Begins reading the stream and logging data to the conosole.
        :param path: File location of the file being streamed.
        """
        try:
            # Read in the stream and parse payloads
            stream = open(path, 'rb')
            byte_stream = io.BytesIO(stream.read())
            byte_stream.seek(0)

            while True:
                if byte_stream.getbuffer().nbytes > 0xf:
                    break
            byte_stream.seek(0xf)
            payload_sizes = self.game._parse_event_payloads(byte_stream)

            # Adaptation from game.py
            while True:
                if self.kill:
                    break
                # Calculate the event prior to entering this
                if byte_stream.getbuffer().nbytes - byte_stream.tell() < payload_sizes[max(payload_sizes, key=payload_sizes.get)]:
                    byte_stream.close()

                    stream = open(path, 'rb')
                    byte_stream = io.BytesIO(stream.read()) # Need to find a method to continually stream without interruption 
                    byte_stream.seek(self.stream_ptr)
                    continue

                event = self.game._parse_event(byte_stream, payload_sizes) 
                self.mutex.acquire()
                if isinstance(event, evt.Frame.Event):
                    frame_index = len(self.frames)
                    self.frames.append(evt.Frame(event.id.frame))

                    port = self.frames[frame_index].ports[event.id.port]
                    if not port:
                        port = evt.Frame.Port()
                        self.frames[frame_index].ports[event.id.port] = port

                    if event.id.is_follower:
                        if port.follower is None:
                            port.follower = evt.Frame.Port.Data()
                        data = port.follower
                    else:
                        data = port.leader

                    if isinstance(event.data, evt.Frame.Port.Data.Pre):
                        data.pre = event.data
                    elif isinstance(event.data, evt.Frame.Port.Data.Post):
                        data.post = event.data
                    else:
                        raise Exception('unknown frame data type: %s' % event.data)
                elif isinstance(event, evt.Start):
                    self.start = event
                elif isinstance(event, evt.End):
                    self.end = event
                else:
                    # Soft exit, no raising
                    raise Exception('unexpected event: %s' % event)

                # read in the stream
                if self.stream_ptr is None:
                    self.stream_ptr = byte_stream.tell()
                else:
                    self.stream_ptr += byte_stream.tell() - self.stream_ptr
                self.mutex.release()

        except EOFError:
            pass

    def read(self, path):
        if self.thread is not None:
            warn('Single thread per LiveGame object, for now =)')
            return
        self.thread = Thread(target=self._read_stream, args=(path,))
        self.thread.start()

    def collect(self):
        """
        Flushes the frame queue accumulated and resets it back to empty.
        :return: List containing event data
        """
        self.mutex.acquire()
        transferred = self.frames[:]
        self.frames = []
        self.mutex.release()
        return transferred

    def close(self):
        """
        Closes the thread down by outside entity.
        """
        if self.thread is not None:
            self.kill = True