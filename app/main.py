from conversation.session import ConversationSession


def main():
    session = ConversationSession.create()

    print(
        f"Session Started: {session.session_id}"
    )


if __name__ == "__main__":
    main()