from __future__ import annotations

import tiktoken



def count_tokens(
    text: str,
    model: str = "gpt-4o-mini",
) -> int:

    try:

        encoding = (
            tiktoken
            .encoding_for_model(model)
        )


    except Exception:

        encoding = (
            tiktoken
            .get_encoding(
                "cl100k_base"
            )
        )


    return len(
        encoding.encode(
            text
        )
    )



def messages_to_text(
    messages: list[dict],
) -> str:

    parts = []


    for message in messages:

        content = message.get(
            "content",
            "",
        )


        if content:

            parts.append(
                str(content)
            )


    return "\n".join(parts)



def estimate_usage(
    messages,
    answer,
    model="gpt-4o-mini",
):

    prompt_text = messages_to_text(
        messages
    )


    prompt_tokens = count_tokens(
        prompt_text,
        model,
    )


    completion_tokens = count_tokens(
        answer,
        model,
    )


    return {

        "prompt_tokens":
            prompt_tokens,


        "completion_tokens":
            completion_tokens,


        "total_tokens":
            prompt_tokens
            +
            completion_tokens,
    }