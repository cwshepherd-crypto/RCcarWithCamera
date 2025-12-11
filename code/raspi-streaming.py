from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput
import socket
import threading


class StreamingOutput:
    def __init__(self, conn):
        self.conn = conn
        self.lock = threading.Lock()

    def write(self, buf):
        with self.lock:
            try:
                self.conn.sendall(buf)
            except (BrokenPipeError, ConnectionResetError):
                return 0
            return len(buf)

    def flush(self):
        pass


def main():
    # Set up TCP server
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("0.0.0.0", 8554))
    server_socket.listen(1)

    print("waiting for connection on port 8554")
    conn, addr = server_socket.accept()
    print(f"connected to {addr}")

    # Initialize camera
    picam2 = Picamera2()
    config = picam2.create_video_configuration(main={"size": (640, 480)})
    picam2.configure(config)

    # Create encoder and output
    encoder = MJPEGEncoder(bitrate=5_000_000)
    output = StreamingOutput(conn)

    try:
        picam2.start_recording(encoder, FileOutput(output))
        print("streaming... (ctrl-c to stop)")

        while True:
            pass  # Keep streaming

    except KeyboardInterrupt:
        print("stopping...")
    finally:
        picam2.stop_recording()
        conn.close()
        server_socket.close()


if __name__ == "__main__":
    main()
