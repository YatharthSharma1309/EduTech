"""
LaTeX / HTML math → plain Unicode conversion.
Handles the output commonly produced by vision models.
"""

import re

# ── Lookup tables ─────────────────────────────────────────────────────────────

_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ",
    "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ",
    "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "chi": "χ", "psi": "ψ", "omega": "ω",
    "Alpha": "Α", "Beta": "Β", "Gamma": "Γ", "Delta": "Δ",
    "Epsilon": "Ε", "Theta": "Θ", "Lambda": "Λ", "Mu": "Μ",
    "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}

_SYMBOLS = {
    "times": "×", "div": "÷", "pm": "±", "mp": "∓",
    "cdot": "·", "leq": "≤", "geq": "≥", "neq": "≠",
    "approx": "≈", "equiv": "≡", "infty": "∞",
    "sqrt": "√", "in": "∈", "notin": "∉",
    "subset": "⊂", "supset": "⊃", "cup": "∪", "cap": "∩",
    "forall": "∀", "exists": "∃", "nabla": "∇",
    "partial": "∂", "int": "∫", "sum": "Σ", "prod": "Π",
    "rightarrow": "→", "leftarrow": "←", "Rightarrow": "⇒",
    "Leftarrow": "⇐", "leftrightarrow": "↔",
    "ldots": "…", "cdots": "⋯", "therefore": "∴", "because": "∵",
    "angle": "∠", "perp": "⊥", "parallel": "∥",
    "triangle": "△", "circ": "°",
}

_SUP = str.maketrans("0123456789+-=()abcdefghijklmnoprstuvwxyzABCDEFGHIJKLMNOPRSTUVWXYZ",
                     "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻᴬᴮᶜᴰᴱᶠᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿˢᵀᵁᵛᵂˣʸᶻ")

_SUB = str.maketrans("0123456789aeiourhlmnpst",
                     "₀₁₂₃₄₅₆₇₈₉ₐₑᵢₒᵤᵣₕₗₘₙₚₛₜ")


# ── Public API ────────────────────────────────────────────────────────────────

def latex_to_unicode(text: str) -> str:
    """Best-effort conversion of LaTeX/HTML math to Unicode."""
    text = _strip_html_tags(text)
    text = _convert_math_blocks(text)
    text = _convert_commands(text)
    text = _convert_frac(text)
    text = _convert_sqrt(text)
    text = _convert_scripts(text)
    return text.strip()


# ── Internals ─────────────────────────────────────────────────────────────────

def _strip_html_tags(text: str) -> str:
    text = re.sub(r"<sup>(.*?)</sup>", lambda m: m.group(1).translate(_SUP), text, flags=re.IGNORECASE)
    text = re.sub(r"<sub>(.*?)</sub>", lambda m: m.group(1).translate(_SUB), text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return text


def _convert_math_blocks(text: str) -> str:
    # Strip math delimiters, keep inner content for further processing
    for pat in [r"\\\[(.+?)\\\]", r"\\\((.+?)\\\)", r"\$\$(.+?)\$\$", r"\$(.+?)\$"]:
        text = re.sub(pat, lambda m: m.group(1), text, flags=re.DOTALL)
    return text


def _convert_commands(text: str) -> str:
    # Greek letters
    for name, sym in _GREEK.items():
        text = re.sub(rf"\\{name}\b", sym, text)
    # Math symbols
    for name, sym in _SYMBOLS.items():
        text = re.sub(rf"\\{name}\b", sym, text)
    # Remove remaining unknown \commands
    text = re.sub(r"\\[a-zA-Z]+\b", "", text)
    return text


def _convert_frac(text: str) -> str:
    def _replace(m):
        num = m.group(1).strip("{}")
        den = m.group(2).strip("{}")
        return f"{num}/{den}"
    return re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", _replace, text)


def _convert_sqrt(text: str) -> str:
    text = re.sub(r"\\sqrt\[([^\]]+)\]\{([^}]+)\}", r"\2^(1/\1)", text)
    text = re.sub(r"\\sqrt\{([^}]+)\}", r"√\1", text)
    return text


def _convert_scripts(text: str) -> str:
    # Braced: x^{abc}, x_{abc}
    def _sup_braced(m):
        inner = m.group(1)
        try:
            return inner.translate(_SUP)
        except Exception:
            return f"^{inner}"

    def _sub_braced(m):
        inner = m.group(1)
        try:
            return inner.translate(_SUB)
        except Exception:
            return f"_{inner}"

    text = re.sub(r"\^\{([^}]+)\}", _sup_braced, text)
    text = re.sub(r"_\{([^}]+)\}", _sub_braced, text)

    # Single char: x^2, x_2
    text = re.sub(r"\^(.)", lambda m: m.group(1).translate(_SUP), text)
    text = re.sub(r"_(.)", lambda m: m.group(1).translate(_SUB), text)

    return text
