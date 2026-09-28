"""A deliberately small, versioned normalizer; not Open ASR Leaderboard WER."""

import unicodedata


def words(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).casefold()
    return "".join(" " if unicodedata.category(c).startswith("P") else c for c in text).split()


def errors(reference: str, hypothesis: str) -> tuple[int, int]:
    ref, hyp = words(reference), words(hypothesis)
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        current = [i]
        for j, h in enumerate(hyp, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (r != h)))
        previous = current
    return previous[-1], len(ref)
