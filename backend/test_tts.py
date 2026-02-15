from modules.synthesizer import synthesize_audio
import os


def test_synthesis():
    script = [
        {"speaker": "A", "text": "こんにちは。これはkokoro-onnxの日本語読み上げテストです。"},
        {"speaker": "B", "text": "音声が自然に聞こえるか、速度や抑揚も含めて確認してみましょう。"},
    ]

    output_file = "test_output.wav"
    print(f"Synthesizing to {output_file}...")
    synthesize_audio(script, output_file)

    if os.path.exists(output_file):
        print(f"Success! {output_file} created.")
    else:
        print("Failed to create audio file.")


if __name__ == "__main__":
    test_synthesis()
