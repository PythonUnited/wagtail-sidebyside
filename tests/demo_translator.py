"""Fake machine translation for the demo site (tests/demo.py)."""

from wagtail_sidebyside.translators import Translator, Usage

PHRASES = {
    "Omelette du fromage": "Cheese omelette",
    "La recette": "The recipe",
    "Bienvenue au laboratoire": "Welcome to the laboratory",
    "Recettes": "Recipes",
    "<p>Battez trois oeufs, ajoutez <b>beaucoup de fromage</b> et faites cuire "
    "a feu doux. Voir aussi "
    '<a href="https://fr.wikipedia.org/wiki/Omelette">l\'omelette</a>.</p>': (
        "<p>Beat three eggs, add <b>lots of cheese</b> and cook over a low heat. "
        'See also <a href="https://en.wikipedia.org/wiki/Omelette">the omelette</a>.'
        "</p>"
    ),
    "<p>Laboratoire du fromage, Paris</p>"
    '<p><a href="mailto:fromage@example.com">fromage@example.com</a></p>': (
        "<p>Cheese laboratory, Paris</p>"
        '<p><a href="mailto:fromage@example.com">fromage@example.com</a></p>'
    ),
}


class DemoTranslator(Translator):
    """Fake machine translation: known phrases, otherwise marked as English."""

    def translate(self, items, source, target, glossary="", instructions=""):
        texts = [PHRASES.get(text, f"[EN] {text}") for text, _is_html in items]
        return texts, Usage(10 * len(items), 10 * len(items))
