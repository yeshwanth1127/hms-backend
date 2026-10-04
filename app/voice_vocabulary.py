"""Forgiving, discoverable vocabulary matching for voice catalogue filters."""

import re
import unicodedata
from difflib import SequenceMatcher


DEPARTMENT_ALIAS_GROUPS = (
    ({"general medicine", "primary care"},
     {"general medicine", "primary care", "family medicine", "internal medicine",
      "general physician", "physician", "gp"}),
    ({"cardiology", "heart health"},
     {"cardiology", "cardiac", "heart", "heart care", "cardiologist"}),
    ({"metabolic", "metabolic health"},
     {"metabolic", "weight", "weight management", "endocrinology", "diabetes", "thyroid"}),
    ({"orthopedics", "joint care"},
     {"orthopedics", "orthopaedics", "ortho", "bones", "bone", "joints", "joint care",
      "sports injury", "spine"}),
    ({"dermatology", "skin care"},
     {"dermatology", "dermatologist", "skin", "skin care"}),
    ({"neurology", "mental health"},
     {"neurology", "neurologist", "neuro", "brain", "mental health", "psychiatry",
      "psychiatrist"}),
    ({"pediatrics", "child health"},
     {"pediatrics", "paediatrics", "pediatrician", "paediatrician", "child", "children",
      "child health", "kids"}),
    ({"ent", "ear nose throat"},
     {"ent", "ear nose throat", "ear", "nose", "throat", "otolaryngology"}),
    ({"dental", "oral maxillofacial"},
     {"dental", "dentist", "dentistry", "oral", "teeth", "tooth", "maxillofacial"}),
    ({"ophthalmology", "eye care"},
     {"ophthalmology", "ophthalmologist", "eye", "eyes", "eye care", "vision"}),
)

MATCH_FILLER_WORDS = {
    "a", "an", "at", "branch", "clinic", "hospital", "in", "location", "near", "please", "the",
}


def normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    ascii_value = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_value.casefold()))


def department_synonyms(department) -> list[str]:
    identity = {normalize(department.slug), normalize(department.name)}
    aliases: set[str] = set()
    for selectors, values in DEPARTMENT_ALIAS_GROUPS:
        normalized_selectors = {normalize(value) for value in selectors}
        if any(selector == candidate or selector in candidate
               for selector in normalized_selectors for candidate in identity):
            aliases.update(values)
    aliases.update({department.slug.replace("-", " "), department.name})
    return sorted(aliases, key=lambda value: (normalize(value), value))


def branch_synonyms(branch) -> list[str]:
    # Branch vocabulary is deliberately derived from the live catalogue. It is
    # per-hospital data and must not be encoded in the voice integration.
    values = {branch.slug.replace("-", " "), branch.name, branch.area}
    return sorted((value for value in values if value), key=lambda value: (normalize(value), value))


def best_matches(query: str, items, variants_for) -> list:
    """Return the best reasonable matches, or [] when vocabulary is unknown."""
    needle = normalize(query)
    if not needle:
        return []
    needle_tokens = set(needle.split()) - MATCH_FILLER_WORDS
    ranked = []
    for item in items:
        best = 0.0
        for raw_variant in variants_for(item):
            variant = normalize(raw_variant)
            if not variant:
                continue
            if needle == variant:
                score = 100.0
            elif len(needle) >= 3 and (needle in variant or variant in needle):
                score = 90.0 - min(abs(len(needle) - len(variant)), 20) / 10
            else:
                variant_tokens = set(variant.split()) - MATCH_FILLER_WORDS
                if needle_tokens and variant_tokens and (
                    needle_tokens <= variant_tokens or variant_tokens <= needle_tokens
                ):
                    overlap_score = 88.0
                else:
                    overlap = len(needle_tokens & variant_tokens) / max(
                        len(needle_tokens | variant_tokens), 1,
                    )
                    overlap_score = overlap * 80.0
                ratio = SequenceMatcher(None, needle, variant).ratio()
                score = max(overlap_score, ratio * 70.0 if ratio >= 0.78 else 0.0)
            best = max(best, score)
        if best >= 55.0:
            ranked.append((best, item))
    if not ranked:
        return []
    highest = max(score for score, _ in ranked)
    return [item for score, item in ranked if score >= highest - 0.01]
