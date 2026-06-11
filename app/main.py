import pandas as pd

from app.orchestrator.intelligence import (
    IntelligenceOrchestrator
)


def main():

    orchestrator = IntelligenceOrchestrator()

    df = pd.read_csv(
        "dataset/queries_test.csv"
    )

    df.columns = df.columns.str.strip()

    audio_files = (
        df["queries"]
        .dropna()
        .tolist()
    )

    for audio_file in audio_files:

        audio_path = (
            f"recordings/{audio_file}"
        )

        print("\n" + "=" * 60)
        print(f"PROCESSING: {audio_file}")
        print("=" * 60)

        result = orchestrator.process_audio(
            audio_path
        )

        print("\nTRANSCRIPT:")
        print(result["transcript"])

        print("\nRESPONSE:")
        print(result["response"])


if __name__ == "__main__":
    main()