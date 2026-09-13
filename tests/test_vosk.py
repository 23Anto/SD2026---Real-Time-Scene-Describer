import socket
import json
import time
import numpy as np
import sounddevice as sd
from vosk import Model, KaldiRecognizer

# --- Configuration ---
# NOTE: this must be a *local* address to bind to, not the ESP32's address/URL.
# "" or "0.0.0.0" means "listen on all network interfaces of this machine".
UDP_IP = "0.0.0.0"
UDP_PORT = 3333          # Match the port your ESP32 is sending to
SAMPLE_RATE = 16000      # 16kHz matches Vosk and your config
CHANNELS = 1             # Mono
DTYPE = 'int16'          # 2 bytes per sample

CHUNK_SIZE = 512
BYTES_PER_SAMPLE = 2
BUFFER_SIZE = CHUNK_SIZE * BYTES_PER_SAMPLE * CHANNELS

# How long we can go without a packet before warning "no audio received"
NO_DATA_TIMEOUT = 3.0    # seconds
# Socket recv timeout, so the loop can periodically check for silence/timeouts
SOCKET_TIMEOUT = 1.0     # seconds
# RMS level below which we consider a packet "silent" (tune to your mic/gain)
SILENCE_RMS_THRESHOLD = 50

# Initialize UDP Socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.settimeout(SOCKET_TIMEOUT)
print(f"Listening for UDP audio on port {UDP_PORT}...")


def rms_level(data: bytes) -> float:
    """Compute RMS amplitude of a chunk of int16 PCM audio."""
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float64)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples ** 2)))


def main():
    # 1. Load the Vosk Model
    try:
        print("Loading Vosk model... (This may take a few seconds)")
        model = Model("model")
        recognizer = KaldiRecognizer(model, SAMPLE_RATE)
    except Exception as e:
        print(f"Error loading model: {e}")
        print("Please ensure your model folder is unzipped and named 'model' in this directory.")
        return

    # 2. Open an Asynchronous Output Stream for Playback
    output_stream = sd.RawOutputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE
    )

    print("\n>>> System active. Listening for ESP32 audio... (Ctrl+C to stop) <<<\n")

    # --- Reception tracking state ---
    packet_count = 0
    last_packet_time = None
    warned_no_data = False
    last_stats_time = time.time()

    try:
        output_stream.start()

        while True:
            # 3. Receive raw bytes from ESP32 over UDP (with timeout, so we can
            #    detect "no data" instead of blocking forever)
            try:
                data, addr = sock.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                data = None

            now = time.time()

            if data:
                packet_count += 1
                last_packet_time = now
                warned_no_data = False

                level = rms_level(data)
                status = "SILENT" if level < SILENCE_RMS_THRESHOLD else "audio"

                # Lightweight per-packet confirmation, once a second-ish worth
                if packet_count % 20 == 0:
                    print(f"[RX] pkt#{packet_count} from {addr} | {len(data)} bytes | "
                          f"RMS={level:.0f} ({status})")

                # 4. Playback the audio in real-time
                output_stream.write(data)

                # 5. Feed the exact same raw bytes into Vosk for Speech-to-Text
                if recognizer.AcceptWaveform(data):
                    result_json = json.loads(recognizer.Result())
                    text = result_json.get("text", "")
                    if text:
                        print(f"\nFinal Text: {text}")
                else:
                    partial_json = json.loads(recognizer.PartialResult())
                    partial_text = partial_json.get("partial", "")
                    if partial_text:
                        print(f"Live: {partial_text}", end="\r", flush=True)
            else:
                # No packet arrived within SOCKET_TIMEOUT seconds
                if last_packet_time is None:
                    elapsed_since_start = now - last_stats_time
                    if elapsed_since_start > NO_DATA_TIMEOUT and not warned_no_data:
                        print(f"\n[WARN] No audio received yet from any ESP32. "
                              f"Check IP/port/network (listening on 0.0.0.0:{UDP_PORT}).")
                        warned_no_data = True
                elif (now - last_packet_time) > NO_DATA_TIMEOUT and not warned_no_data:
                    print(f"\n[WARN] No audio received for {NO_DATA_TIMEOUT:.0f}s "
                          f"(last packet at {time.strftime('%H:%M:%S', time.localtime(last_packet_time))}). "
                          f"ESP32 may have stopped streaming.")
                    warned_no_data = True

            # Periodic summary every ~10 seconds
            if now - last_stats_time > 10:
                print(f"\n[STATS] {packet_count} packets received in the last check window.")
                last_stats_time = now

    except KeyboardInterrupt:
        print("\nStopping audio detection...")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
    finally:
        output_stream.stop()
        output_stream.close()
        sock.close()


if __name__ == "__main__":
    main()