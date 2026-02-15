import os
import requests


def download_file(url, path):
    print(f"Downloading {path}...")
    response = requests.get(url, stream=True)
    response.raise_for_status()
    block_size = 1024

    with open(path, "wb") as file:
        for data in response.iter_content(block_size):
            file.write(data)

    print(f"Downloaded {path}")


def setup_kokoro():
    # Ensure modules directory exists
    base_dir = os.path.dirname(os.path.abspath(__file__))
    target_dir = os.path.join(base_dir, "modules", "kokoro-data")
    os.makedirs(target_dir, exist_ok=True)

    model_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
    voices_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

    model_path = os.path.join(target_dir, "kokoro-v1.0.onnx")
    voices_path = os.path.join(target_dir, "voices-v1.0.bin")

    if not os.path.exists(model_path):
        download_file(model_url, model_path)
    else:
        print("Model already exists.")

    if not os.path.exists(voices_path):
        download_file(voices_url, voices_path)
    else:
        print("Voices file already exists.")


if __name__ == "__main__":
    setup_kokoro()
