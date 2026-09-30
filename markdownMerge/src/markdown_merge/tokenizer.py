import tiktoken


class TokenCounter:
    def __init__(
        self,
        model: str | None = "gpt-4o",
        encoding_name: str | None = None,
    ) -> None:
        if encoding_name is not None:
            self.encoding = tiktoken.get_encoding(encoding_name)
        elif model is not None:
            self.encoding = tiktoken.encoding_for_model(model)
        else:
            raise ValueError("Either model or encoding_name must be provided.")

    def count(self, text: str) -> int:
        return len(
            self.encoding.encode(
                text,
                disallowed_special=(),
            )
        )


def count_tokens(
    text: str,
    *,
    model: str | None = "gpt-4o",
    encoding_name: str | None = None,
) -> int:
    counter = TokenCounter(
        model=model,
        encoding_name=encoding_name,
    )
    return counter.count(text)
