from __future__ import annotations

import re
import unicodedata

from tiktok_automation.schemas import CandidateCollection, ClipCandidate, TranscriptResult
from tiktok_automation.utils import overlap_ratio, write_json


HOOK_MARKERS = {
    "por que",
    "porque",
    "segredo",
    "erro",
    "ninguem",
    "nunca",
    "sempre",
    "como",
    "3 passos",
    "passo a passo",
    "maior problema",
    "o problema",
    "eu fiz",
    "aprendi",
    "quase",
    "absurdo",
    "nao sabia",
}

ENERGY_MARKERS = {
    "dinheiro",
    "vendas",
    "negocio",
    "empresa",
    "cliente",
    "resultado",
    "crise",
    "medo",
    "caro",
    "milhao",
    "viral",
    "falhou",
    "funciona",
    "funcionou",
    "aprendizado",
    "choque",
}

CATEGORY_RULES: list[tuple[set[str], list[str]]] = [
    ({"venda", "vendas", "cliente", "comercial"}, ["vendas", "negocios", "empreendedorismo"]),
    ({"dinheiro", "investir", "financa", "lucro"}, ["financas", "dinheiro", "investimentos"]),
    ({"podcast", "entrevista", "episodio"}, ["podcast", "cortes", "entrevista"]),
    ({"ia", "ai", "modelo", "chatgpt", "openai", "saas"}, ["ia", "tecnologia", "saas"]),
    ({"psicologia", "ansiedade", "mental", "emocional"}, ["psicologia", "comportamento", "mentalidade"]),
]

OPENING_FILLERS = {
    "ah",
    "ai",
    "aí",
    "ahh",
    "eh",
    "e",
    "mas",
    "entao",
    "então",
    "oxe",
    "ixi",
    "hum",
    "hã",
    "opa",
    "olha",
    "ó",
    "po",
    "pô",
    "mano",
    "cara",
    "rapaziada",
    "galera",
}

STOPWORD_TITLE = OPENING_FILLERS | {"o", "a", "os", "as", "de", "do", "da", "dos", "das", "que", "um", "uma"}


def _strip_accents(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def _normalize_text(text: str) -> str:
    normalized = text.replace(">>", " ")
    normalized = re.sub(r"\[\s*__\s*\]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"\s+([,.!?;:])", r"\1", normalized)
    return normalized.strip()


def _tokenize_words(text: str) -> list[str]:
    return [part for part in _normalize_text(text).split() if part.strip()]


def _low_signal_ratio(tokens: list[str]) -> float:
    if not tokens:
        return 1.0
    lowered = [_strip_accents(token.lower().strip(".,!?;:")) for token in tokens]
    low_signal = sum(1 for token in lowered if token in OPENING_FILLERS)
    return low_signal / len(lowered)


def _repetition_ratio(tokens: list[str]) -> float:
    if len(tokens) <= 1:
        return 0.0
    lowered = [_strip_accents(token.lower().strip(".,!?;:")) for token in tokens if token.strip(".,!?;:")]
    if not lowered:
        return 0.0
    unique_ratio = len(set(lowered)) / len(lowered)
    return 1.0 - unique_ratio


def _words_per_second(text: str, duration_seconds: float) -> float:
    words = _tokenize_words(text)
    return len(words) / max(duration_seconds, 1.0)


def _window_text(segments: list) -> str:
    return _normalize_text(" ".join(segment.text.strip() for segment in segments if segment.text.strip()))


def _is_low_signal_text(text: str) -> bool:
    tokens = _tokenize_words(text)
    if not tokens:
        return True
    if len(tokens) <= 2 and _low_signal_ratio(tokens) >= 0.5:
        return True
    if len(tokens) <= 3 and not re.search(r"[0-9?.!]", text):
        lowered = [_strip_accents(token.lower().strip(".,!?;:")) for token in tokens]
        return all(token in OPENING_FILLERS for token in lowered)
    return False


def _trim_window_segments(segments: list, min_duration: float) -> list:
    trimmed = list(segments)

    while len(trimmed) > 1 and _is_low_signal_text(trimmed[0].text):
        candidate_duration = trimmed[-1].end - trimmed[1].start
        if candidate_duration < min_duration:
            break
        trimmed = trimmed[1:]

    while len(trimmed) > 1 and _is_low_signal_text(trimmed[-1].text):
        candidate_duration = trimmed[-2].end - trimmed[0].start
        if candidate_duration < min_duration:
            break
        trimmed = trimmed[:-1]

    while len(trimmed) > 1 and not re.search(r"[.!?]$", trimmed[-1].text):
        candidate_duration = trimmed[-2].end - trimmed[0].start
        if candidate_duration < min_duration:
            break
        if len(_tokenize_words(trimmed[-1].text)) > 8:
            break
        trimmed = trimmed[:-1]

    return trimmed


def _make_title(text: str) -> str:
    normalized = _normalize_text(text)
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", normalized) if sentence.strip()]
    sentence = sentences[0] if sentences else normalized
    tokens = sentence.split()
    while tokens and _strip_accents(tokens[0].lower().strip(".,!?;:")) in STOPWORD_TITLE:
        tokens = tokens[1:]
    title = " ".join(tokens[:10]).strip()
    if len(title.split()) < 3 and len(sentences) > 1:
        backup_tokens = sentences[1].split()
        title = " ".join(backup_tokens[:10]).strip()
    title = title[:72].rstrip(" ,;:-")
    return title or "Corte com potencial"


def _make_hook(text: str) -> str:
    normalized = _normalize_text(text)
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", normalized) if sentence.strip()]
    for sentence in sentences[:2]:
        tokens = sentence.split()
        if len(tokens) >= 3:
            return " ".join(tokens[:8]).upper()[:56]
    return _make_title(normalized).upper()[:56]


def _infer_hashtags(text: str) -> list[str]:
    lowered_tokens = {
        _strip_accents(token.lower().strip(".,!?;:"))
        for token in _tokenize_words(text)
        if token.strip(".,!?;:")
    }
    tags = ["cortes"]
    for keywords, extra_tags in CATEGORY_RULES:
        if any(keyword in lowered_tokens for keyword in keywords):
            tags.extend(extra_tags)
    deduped: list[str] = []
    for tag in tags:
        if tag not in deduped:
            deduped.append(tag)
    return deduped[:5]


def _score_candidate(
    start: float,
    end: float,
    text: str,
    opening_text: str,
    closing_text: str,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    normalized_text = _normalize_text(text)
    lowered = _strip_accents(normalized_text.lower())
    opener = lowered[:160]
    duration = end - start
    score = 0.0
    tokens = _tokenize_words(normalized_text)
    opening_tokens = _tokenize_words(opening_text)
    closing_tokens = _tokenize_words(closing_text)

    hook_hits = sum(1 for marker in HOOK_MARKERS if marker in opener)
    if hook_hits:
        score += min(3.0, hook_hits * 0.8)
        reasons.append("abertura com curiosidade ou conflito")

    if "?" in normalized_text[:120]:
        score += 1.4
        reasons.append("abre com pergunta")

    if re.search(r"\d", normalized_text[:120]):
        score += 0.9
        reasons.append("usa numero logo no inicio")

    energy_hits = sum(1 for marker in ENERGY_MARKERS if marker in lowered)
    if energy_hits:
        score += min(2.2, energy_hits * 0.35)
        reasons.append("tema com carga emocional ou pratica forte")

    wps = _words_per_second(text, duration)
    if 2.1 <= wps <= 4.6:
        score += 2.0
        reasons.append("ritmo bom para short-form")
    elif wps < 1.5:
        score -= 1.6
    elif wps > 5.5:
        score -= 0.8

    if 22 <= duration <= 40:
        score += 1.4
        reasons.append("duracao boa para discovery")
    elif duration > 45:
        score -= 0.7

    if normalized_text.endswith("?") or "parte 2" in lowered or "continua" in lowered:
        score += 0.7
        reasons.append("fecha deixando gancho")

    if len(tokens) >= 45:
        score += 0.5

    opening_low_signal = _low_signal_ratio(opening_tokens)
    if opening_low_signal <= 0.15 and len(opening_tokens) >= 4:
        score += 0.9
        reasons.append("entra direto no assunto")
    elif opening_low_signal >= 0.4:
        score -= 1.2

    repetition = _repetition_ratio(tokens)
    if repetition <= 0.18:
        score += 0.8
        reasons.append("texto menos repetitivo")
    elif repetition >= 0.32:
        score -= 2.2

    if re.search(r"[.!?]$", closing_text):
        score += 0.7
        reasons.append("termina em fechamento mais limpo")
    else:
        score -= 1.0

    if len(closing_tokens) <= 2 and _low_signal_ratio(closing_tokens) >= 0.5:
        score -= 0.8

    return score, reasons


def build_candidates(
    transcript: TranscriptResult,
    top_k: int = 5,
    min_duration: float = 16.0,
    max_duration: float = 42.0,
) -> CandidateCollection:
    raw: list[ClipCandidate] = []
    segments = transcript.segments

    for start_index in range(len(segments)):
        for end_index in range(start_index, len(segments)):
            start = segments[start_index].start
            end = segments[end_index].end
            duration = end - start
            if duration > max_duration:
                break
            if duration < min_duration:
                continue

            window_segments = _trim_window_segments(segments[start_index : end_index + 1], min_duration=min_duration)
            if not window_segments:
                continue
            start = window_segments[0].start
            end = window_segments[-1].end
            duration = end - start
            if duration < min_duration or duration > max_duration:
                continue
            text = _window_text(window_segments)
            if len(_tokenize_words(text)) < 30:
                continue

            score, reasons = _score_candidate(
                start,
                end,
                text,
                opening_text=window_segments[0].text,
                closing_text=window_segments[-1].text,
            )
            title = _make_title(text)
            hashtags = _infer_hashtags(text)
            hook = _make_hook(text)
            caption_title = title.rstrip(".!? ")
            raw.append(
                ClipCandidate(
                    rank=0,
                    title=title,
                    hook=hook,
                    start=start,
                    end=end,
                    duration_seconds=duration,
                    score=round(score, 3),
                    excerpt=text[:280],
                    reasons=reasons,
                    suggested_caption=f"{caption_title}. " + " ".join(f"#{tag}" for tag in hashtags[:4]),
                    suggested_hashtags=hashtags,
                )
            )

    raw.sort(key=lambda candidate: candidate.score, reverse=True)

    selected: list[ClipCandidate] = []
    for candidate in raw:
        if any(
            overlap_ratio(
                candidate.start,
                candidate.end,
                existing.start,
                existing.end,
            )
            > 0.55
            for existing in selected
        ):
            continue
        selected.append(candidate)
        if len(selected) >= top_k:
            break

    ranked: list[ClipCandidate] = []
    for index, candidate in enumerate(selected, start=1):
        ranked.append(
            ClipCandidate(
                rank=index,
                title=candidate.title,
                hook=candidate.hook,
                start=candidate.start,
                end=candidate.end,
                duration_seconds=candidate.duration_seconds,
                score=candidate.score,
                excerpt=candidate.excerpt,
                reasons=candidate.reasons,
                suggested_caption=candidate.suggested_caption,
                suggested_hashtags=candidate.suggested_hashtags,
            )
        )

    return CandidateCollection(
        run_id=transcript.run_id,
        source_video_path=transcript.source_video_path,
        candidates=ranked,
    )


def persist_candidates(collection: CandidateCollection, path) -> None:
    write_json(path, collection.model_dump(mode="json"))
