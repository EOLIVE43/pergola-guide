"""
image_utils.py — Gestion des images responsive pour pergola-guide.fr

Objectif : servir des images adaptées à la taille de l'écran (srcset) pour
optimiser les Core Web Vitals (LCP, total bytes), tout en gardant une version
1200px disponible pour Google Discover (exigence stricte d'indexation).
"""

import re
from pathlib import Path

try:
    from PIL import Image
    PILLOW_OK = True
except ImportError:
    PILLOW_OK = False

# ─── CONFIG TAILLES ──────────────────────────────────────────
TAILLES_VARIANTES = [400, 800, 1200]
QUALITE_WEBP = {400: 80, 800: 82, 1200: 85}
RATIO_W_H = 3 / 2

# ─── RÔLES D'IMAGE ──────────────────────────────────────────
SIZES_PAR_ROLE = {
    "hero":      "(max-width: 600px) 100vw, (max-width: 1200px) 90vw, 1100px",
    "article":   "(max-width: 600px) 100vw, (max-width: 900px) 90vw, 820px",
    "card":      "(max-width: 600px) 90vw, (max-width: 900px) 45vw, 380px",
    "thumb":     "(max-width: 600px) 90vw, (max-width: 900px) 45vw, 240px",
    "default":   "(max-width: 600px) 100vw, 800px",
}


def _decomposer_url(url_ou_chemin):
    """Sépare une URL/chemin en (base_sans_extension, extension)."""
    m = re.match(r'^(.+?)(\.[a-zA-Z0-9]+)$', url_ou_chemin)
    if not m:
        return url_ou_chemin, ""
    base, ext = m.group(1), m.group(2)
    base = re.sub(r'-(400|800|1200)$', '', base)
    return base, ext


def url_variante(url_source, taille):
    """Renvoie l'URL d'une variante spécifique."""
    base, ext = _decomposer_url(url_source)
    return f"{base}-{taille}{ext}"


def url_1200_pour_og(url_source):
    """Renvoie l'URL de la variante 1200px pour og:image et JSON-LD."""
    if url_source.startswith("http") and not url_source.startswith("/"):
        return url_source
    return url_variante(url_source, 1200)


def est_image_locale(url):
    """Vérifie si une URL pointe vers une image locale du site."""
    return url.startswith("/images/") or url.startswith("images/")


def generer_variantes(chemin_source, forcer=False):
    """Génère les 3 variantes (400, 800, 1200) d'une image source."""
    if not PILLOW_OK:
        print("  ⚠️ Pillow non disponible, impossible de générer les variantes")
        return False

    src = Path(chemin_source)
    if not src.exists():
        print(f"  ⚠️ Source introuvable : {chemin_source}")
        return False

    base, ext = _decomposer_url(str(src))

    toutes_existent = all(
        Path(f"{base}-{t}{ext}").exists() for t in TAILLES_VARIANTES
    )
    if toutes_existent and not forcer:
        return False

    try:
        img = Image.open(src)
        largeur_source = img.width

        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        cree = 0
        for taille in TAILLES_VARIANTES:
            chemin_variante = Path(f"{base}-{taille}{ext}")
            if chemin_variante.exists() and not forcer:
                continue

            if largeur_source <= taille:
                img_out = img.copy()
            else:
                hauteur = int(taille / RATIO_W_H)
                img_out = img.resize((taille, hauteur), Image.LANCZOS)

            qualite = QUALITE_WEBP.get(taille, 82)
            img_out.save(
                chemin_variante,
                "WEBP",
                quality=qualite,
                method=6,
            )
            cree += 1

        if cree > 0:
            print(f"  🖼️  {cree} variantes créées pour {src.name}")
        return cree > 0

    except Exception as e:
        print(f"  ⚠️ Erreur génération variantes {chemin_source} : {e}")
        return False


def img_responsive(url_source, alt, role="default",
                   loading="lazy", fetchpriority=None,
                   width=1200, height=800, classe=""):
    """Génère une balise <img> responsive complète avec srcset."""
    alt_safe = alt.replace('"', '&quot;')
    classe_attr = f' class="{classe}"' if classe else ''
    fp_attr = f' fetchpriority="{fetchpriority}"' if fetchpriority else ''

    if not est_image_locale(url_source):
        return (
            f'<img src="{url_source}" alt="{alt_safe}"{classe_attr} '
            f'loading="{loading}"{fp_attr} width="{width}" height="{height}">'
        )

    url_400  = url_variante(url_source, 400)
    url_800  = url_variante(url_source, 800)
    url_1200 = url_variante(url_source, 1200)

    sizes = SIZES_PAR_ROLE.get(role, SIZES_PAR_ROLE["default"])
    src_fallback = url_800

    return (
        f'<img src="{src_fallback}" '
        f'srcset="{url_400} 400w, {url_800} 800w, {url_1200} 1200w" '
        f'sizes="{sizes}" '
        f'alt="{alt_safe}"{classe_attr} '
        f'loading="{loading}"{fp_attr} '
        f'width="{width}" height="{height}">'
    )


def optimiser_toutes_images(dossiers=None, forcer=False):
    """Mode batch : parcourt tous les dossiers images et génère les variantes."""
    if dossiers is None:
        dossiers = ["images/home", "images/piliers", "images/secondaires", "images/blog"]

    nb_images = 0
    nb_variantes = 0

    for dossier in dossiers:
        p = Path(dossier)
        if not p.exists():
            print(f"  ⊘ {dossier} n'existe pas, ignoré")
            continue

        for img_path in p.glob("*.webp"):
            nom = img_path.stem
            if re.search(r'-(400|800|1200)$', nom):
                continue

            nb_images += 1
            avant = sum(
                1 for t in TAILLES_VARIANTES
                if Path(f"{img_path.parent}/{nom}-{t}.webp").exists()
            )
            if generer_variantes(str(img_path), forcer=forcer):
                apres = sum(
                    1 for t in TAILLES_VARIANTES
                    if Path(f"{img_path.parent}/{nom}-{t}.webp").exists()
                )
                nb_variantes += (apres - avant)

    return nb_images, nb_variantes
