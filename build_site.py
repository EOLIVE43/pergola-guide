#!/usr/bin/env python3
"""
build_site.py — Version finale complète
Améliorations :
- Replicate FLUX.1-dev (piliers) / FLUX.1-schnell (secondaires+blog)
- 2 images sur piliers, 1 sur secondaires+blog, toutes 1200px
- meta robots max-image-preview:large (Google Discover)
- Schemas JSON-LD : FAQPage, BreadcrumbList, HowTo, Article enrichi
- datePublished+dateModified blog, dateModified piliers/secondaires
- Prompts SEO boostés + keywords.json
- Titres blog Discover-friendly
- Maillage statique HTML bidirectionnel
- Liens contextuels dans le corps du texte
- Ancres diversifiées depuis comments_config.json
- Articles similaires en bas des billets
- Ping Google sitemap après publication

URL structure (v2) :
- Accueil         : /index.html
- Pilier          : /{pilier-slug}.html             ex: /pergola-aluminium.html
- Secondaire      : /{pilier-id}/{slug}.html        ex: /aluminium/pergola-aluminium-6x4.html
- Blog            : /blog/{slug}.html
"""

import os, json, re, random, time, urllib.request, urllib.parse
from image_utils import (
    generer_variantes, img_responsive, url_1200_pour_og,
    optimiser_toutes_images
)
import anthropic
from datetime import datetime
from pathlib import Path

# ─── CONFIG ───────────────────────────────────────────────
SITE_URL = "https://pergola-guide.fr"
SITE_NOM  = "Pergola Guide"

# ─── LOGO (style magazine éditorial) ──────────────────────
# Logo typographique inline : "Pergola / GUIDE"
# Rendu pro, responsive, 100% HTML (pas de fichier image à gérer)
SITE_LOGO = (
    '<span class="logo-pergola">Pergola</span>'
    '<span class="logo-slash">/</span>'
    '<span class="logo-guide">GUIDE</span>'
)
SITE_DESCRIPTION_COURTE = "Le guide de référence sur les pergolas en France"

# ─── CONFIG AUTEUR (E-E-A-T, critique pour Google Discover) ──
# Pseudonyme journalistique : protège la vie privée tout en fournissant
# une identité humaine crédible à Google (schema Person).
AUTEUR_NOM        = "Mathias D."
AUTEUR_ROLE       = "Rédacteur en chef — Pergola Guide"
AUTEUR_BIO_COURTE = "Mathias rédige les contenus de Pergola Guide. Passionné d'aménagement extérieur, il étudie depuis plusieurs années le marché français des pergolas : prix, matériaux, réglementation, installation. Son objectif est de vous fournir une information indépendante, à jour et directement utilisable pour votre projet."
AUTEUR_URL        = "/a-propos.html"

# ─── CONFIG ANALYTICS & SEO (remplir sans relancer full) ──
# Une fois ces valeurs remplies, lancer : python build_site.py fix
# → Toutes les pages seront mises à jour en 2 min, sans appel API.

GA4_ID           = "G-67NBZNSJN5"   # Ex: "G-67NBZNSJN5" (depuis Google Analytics 4)
GSC_META_CONTENT = "TqUMY1r1HbqDksIg2vZCJWCOZhZviEKIQ7bHPiDUR0c"   # Ex: "abc123def456xyz" (juste la valeur du content=, pas la balise complète)

# ─── CONFIG ADSENSE ───────────────────────────────────────
# Pour activer AdSense le moment venu :
# 1. Passer ADSENSE_ACTIF = True
# 2. Remplacer ADSENSE_CLIENT par ton vrai ID (ca-pub-XXXXXXXXXXXXXXXX)
# 3. Remplacer chaque ADSENSE_SLOT_xxx par tes vrais IDs de blocs AdSense
# 4. Relancer `python build_site.py fix` (pas besoin de full)
ADSENSE_ACTIF        = False
ADSENSE_CLIENT       = "ca-pub-XXXXXXXXXXXXXXXX"
ADSENSE_SLOT_HAUT    = "1111111111"   # Bloc horizontal haut (responsive)
ADSENSE_SLOT_MILIEU  = "2222222222"   # Bloc in-article (milieu contenu)
ADSENSE_SLOT_BAS     = "3333333333"   # Bloc horizontal bas (avant commentaires)
ADSENSE_SLOT_SIDEBAR = "4444444444"   # Bloc sidebar (300x250)

# ─── FORMATS ÉDITORIAUX DU BLOG ──────────────────────────
# Chaque article du blog est généré selon UN des 4 formats, tirés au sort.
# Objectif : varier la structure pour éviter toute signature "content farm IA"
# et maximiser la protection contre les updates anti-spam Discover.
# Tous les formats CONSERVENT les optimisations Discover (schemas, OG, images, E-E-A-T).
POIDS_FORMATS_BLOG = {
    "guide":        25,  # Guide classique (H2/H3 + prose) — format universel
    "listicle":     25,  # Liste numérotée avec big numbers — perf Discover mobile
    "comparatif":   15,  # Comparatif avec tableau visuel + verdict — "X ou Y"
    "qr":           15,  # Questions/Réponses en accordéons — réglementation/prix
    "cas_pratique": 10,  # Cas concret / étude de cas avec chiffres — très "humain"
    "saisonnier":   10,  # Article saisonnier avec dimension temporelle — anti-IA
}

# Association catégorie → format préféré (si catégorie présente dans sujets.json).
# Si catégorie inconnue, tirage aléatoire selon POIDS_FORMATS_BLOG.
FORMAT_PAR_CATEGORIE = {
    "Erreurs":         "listicle",
    "Astuces":         "listicle",
    "Checklist":       "listicle",
    "Comparaison":     "comparatif",
    "Choix":           "comparatif",
    "Réglementation":  "qr",
    "Permis":          "qr",
    "Assurance":       "qr",
    "Prix":            "qr",
    "Cas pratique":    "cas_pratique",
    "Témoignage":      "cas_pratique",
    "Étude de cas":    "cas_pratique",
    "Saisonnier":      "saisonnier",
    "Printemps":       "saisonnier",
    "Été":             "saisonnier",
    "Automne":         "saisonnier",
    "Hiver":           "saisonnier",
    "Entretien":       "saisonnier",  # souvent lié aux saisons
}

def choisir_format_blog(sujet):
    """Choisit un format éditorial pour l'article selon sa catégorie ou au hasard.
    Garantit une variété structurelle sur le site (protection anti-pattern IA)."""
    # Priorité : si la catégorie a un format dédié, on l'utilise avec 70% de chance
    # (30% de tirage aléatoire pour éviter qu'une catégorie soit 100% listicle)
    categorie = sujet.get("categorie", "")
    if categorie in FORMAT_PAR_CATEGORIE and random.random() < 0.70:
        return FORMAT_PAR_CATEGORIE[categorie]
    # Sinon tirage pondéré
    formats = list(POIDS_FORMATS_BLOG.keys())
    poids   = list(POIDS_FORMATS_BLOG.values())
    return random.choices(formats, weights=poids, k=1)[0]

# ─── BALISES HEAD ANALYTICS & SEO ────────────────────────
def balise_gsc():
    """Meta tag Google Search Console."""
    if not GSC_META_CONTENT:
        return "<!-- GSC : non configuré -->"
    return f'<meta name="google-site-verification" content="{GSC_META_CONTENT}">'

def script_ga4_head():
    """Script GA4 chargé CONDITIONNELLEMENT selon consentement cookies."""
    if not GA4_ID:
        return "<!-- GA4 : non configuré -->"
    # Script Consent Mode v2 + chargement conditionnel
    return f'''<!-- Google Analytics 4 (via Consent Mode v2) -->
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    // Par défaut : tout refusé (RGPD-first)
    gtag('consent', 'default', {{
      'ad_storage': 'denied',
      'ad_user_data': 'denied',
      'ad_personalization': 'denied',
      'analytics_storage': 'denied',
      'functionality_storage': 'granted',
      'security_storage': 'granted',
      'wait_for_update': 500
    }});
    // Relire le consentement déjà stocké
    try {{
      var c = JSON.parse(localStorage.getItem('pg_consent') || 'null');
      if (c) {{
        gtag('consent', 'update', {{
          'ad_storage': c.ads ? 'granted' : 'denied',
          'ad_user_data': c.ads ? 'granted' : 'denied',
          'ad_personalization': c.ads ? 'granted' : 'denied',
          'analytics_storage': c.analytics ? 'granted' : 'denied'
        }});
      }}
    }} catch(e) {{}}
    gtag('js', new Date());
    gtag('config', '{GA4_ID}', {{ 'anonymize_ip': true }});
  </script>
  <script async src="https://www.googletagmanager.com/gtag/js?id={GA4_ID}"></script>'''

def script_adsense_head():
    """Script AdSense dans le <head> — vide si inactif."""
    if not ADSENSE_ACTIF:
        return "<!-- AdSense : inactif pour l'instant -->"
    return (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/' 
            f'adsbygoogle.js?client={ADSENSE_CLIENT}" crossorigin="anonymous"></script>')

def bloc_adsense(slot_id, type_bloc="inArticle"):
    """
    Génère un emplacement publicitaire AdSense.
    Inactif  → div vide avec commentaire (invisible, aucun impact perf)
    Actif    → vrai bloc AdSense responsive
    type_bloc: 'inArticle' | 'horizontal' | 'sidebar'
    """
    if not ADSENSE_ACTIF:
        return (f'\n<!-- [ADSENSE-{type_bloc.upper()}] Emplacement réservé -->\n'
                f'<div class="adsense-bloc adsense-{type_bloc}" aria-hidden="true"></div>\n')
    return f"""
<div class="adsense-bloc adsense-{type_bloc}">
  <ins class="adsbygoogle"
       style="display:block"
       data-ad-client="{ADSENSE_CLIENT}"
       data-ad-slot="{slot_id}"
       data-ad-format="auto"
       data-full-width-responsive="true"></ins>
  <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
</div>"""


# ─── CHARGEMENT DONNÉES ───────────────────────────────────
def charger_architecture():
    with open("architecture.json", encoding="utf-8") as f:
        return json.load(f)

def charger_keywords():
    p = Path("keywords.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

def charger_comments_config():
    p = Path("comments_config.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

def charger_articles():
    p = Path("articles.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

# ─── ANCRES DIVERSIFIÉES ──────────────────────────────────
def ancre_aleatoire(pilier_id, comments_config):
    anchres = comments_config.get("anchres_piliers", {})
    liste = anchres.get(pilier_id, [pilier_id])
    return random.choice(liste)

# ─── KEYWORDS PROMPT ──────────────────────────────────────
def formater_keywords_prompt(pilier_id, keywords):
    if pilier_id not in keywords:
        return ""
    data = keywords[pilier_id]
    top_sec = data.get("secondaires", [])[:15]
    top_lt  = data.get("longue_traine", [])[:10]
    lignes  = ["\n=== DONNÉES SEO RÉELLES (Ahrefs France) ==="]
    lignes.append(f"Mot-clé principal : {data['principal']} ({data['volume_principal']:,} recherches/mois)")
    lignes.append("\nMots-clés secondaires à intégrer naturellement :")
    for kw in top_sec:
        lignes.append(f"  - {kw['kw']} ({kw['vol']:,}/mois, intent: {kw['intent']})")
    lignes.append("\nLongue traîne à couvrir dans H2/H3 :")
    for kw in top_lt:
        lignes.append(f"  - {kw['kw']} ({kw['vol']:,}/mois)")
    lignes.append("\nINSTRUCTIONS SEO OBLIGATOIRES :")
    lignes.append("- Mot-clé principal dans H1, 100 premiers mots, et 3+ fois dans le corps")
    lignes.append("- Chaque mot-clé secondaire apparaît au moins 1 fois naturellement")
    lignes.append("- Longue traîne en H2, H3 ou dans les paragraphes")
    lignes.append("- Structure : 1 H1, 5-7 H2, H3 sous chaque H2, listes <ul>")
    lignes.append("- Densité mot-clé principal : 1-2%")
    lignes.append("===========================================\n")
    return "\n".join(lignes)

# ─── REPLICATE IMAGE ──────────────────────────────────────
def generer_image_replicate(prompt_sujet, modele="schnell", largeur=1200, hauteur=800):
    """Génère une image via Replicate FLUX. modele='dev' ou 'schnell'."""
    api_key = os.environ.get("REPLICATE_API_KEY", "")
    if not api_key:
        return None
    
    model_id = (
        "black-forest-labs/flux-1.1-pro" if modele == "dev"
        else "black-forest-labs/flux-schnell"
    )
    
    prompt = (
        f"Ultra photorealistic {prompt_sujet}, "
        f"professional architectural photography, magazine quality, "
        f"natural daylight, crisp sharp details, wide angle lens, "
        f"no people, no text, no watermark, 16:9 composition"
    )
    
    try:
        # Créer la prédiction
        payload = json.dumps({
            "version": model_id,
            "input": {
                "prompt": prompt,
                "width": largeur,
                "height": hauteur,
                "num_outputs": 1,
                "output_format": "webp",
                "output_quality": 85,
            }
        }).encode()
        
        req = urllib.request.Request(
            "https://api.replicate.com/v1/predictions",
            data=payload,
            headers={
                "Authorization": f"Token {api_key}",
                "Content-Type": "application/json"
            }
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            prediction = json.loads(r.read().decode())
        
        pred_id = prediction.get("id")
        if not pred_id:
            return None
        
        # Poller jusqu'à completion (max 120s)
        for _ in range(60):
            time.sleep(2)
            poll_req = urllib.request.Request(
                f"https://api.replicate.com/v1/predictions/{pred_id}",
                headers={"Authorization": f"Token {api_key}"}
            )
            with urllib.request.urlopen(poll_req, timeout=15) as r:
                result = json.loads(r.read().decode())
            
            status = result.get("status")
            if status == "succeeded":
                output = result.get("output", [])
                if output:
                    return {
                        "url": output[0] if isinstance(output, list) else output,
                        "credit_nom": "IA Generée",
                        "credit_url": "#"
                    }
                break
            elif status in ("failed", "canceled"):
                print(f"  ⚠️ Replicate {status}: {result.get('error')}")
                break
    
    except Exception as e:
        print(f"  ⚠️ Erreur Replicate: {e}")
    
    return None

def recuperer_image_unsplash(query="pergola jardin"):
    """Fallback Unsplash avec images 1200px."""
    access_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    defaut = {
        "url": "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=1200",
        "credit_nom": "Unsplash",
        "credit_url": "https://unsplash.com"
    }
    if not access_key:
        return defaut
    try:
        q   = urllib.parse.quote(query)
        url = (f"https://api.unsplash.com/search/photos"
               f"?query={q}&per_page=10&orientation=landscape&client_id={access_key}")
        req = urllib.request.Request(url, headers={"Accept-Version": "v1"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        results = data.get("results", [])
        if results:
            photo = random.choice(results[:5])
            # Force 1200px
            img_url = re.sub(r'w=\d+', 'w=1200', photo["urls"]["regular"])
            return {
                "url": img_url,
                "credit_nom": photo["user"]["name"],
                "credit_url": photo["user"]["links"]["html"] + "?utm_source=pergola_guide&utm_medium=referral"
            }
    except Exception as e:
        print(f"  ⚠️ Erreur Unsplash: {e}")
    return defaut

def get_image(sujet, modele="schnell", chemin_local=None):
    """Essaie Replicate, fallback Unsplash.

    Si chemin_local est fourni (ex: "images/piliers/pergola-bois-1.webp"),
    l'image est téléchargée dans le repo et l'URL renvoyée pointe vers
    le chemin local absolu (ex: "/images/piliers/pergola-bois-1.webp").
    Cela évite que les URLs Replicate temporaires expirent après 24-48h.
    """
    # Si l'image existe déjà en local, on la réutilise (cache parfait)
    if chemin_local:
        p = Path(chemin_local)
        if p.exists() and p.stat().st_size > 5000:  # fichier non vide
            print(f"  ♻️ Image réutilisée : {chemin_local}")
            return {"url": f"/{chemin_local}", "credit_nom": "IA", "credit_url": "#"}

    img = generer_image_replicate(sujet, modele)
    source = "flux"
    if not img:
        print(f"  📷 Fallback Unsplash")
        img = recuperer_image_unsplash(sujet)
        source = "unsplash"
    else:
        print(f"  🎨 Image FLUX générée")

    # Téléchargement vers le repo si demandé
    if chemin_local and img and img.get("url"):
        if telecharger_image(img["url"], chemin_local):
            # Remplacer l'URL temporaire par le chemin local absolu
            img["url"] = f"/{chemin_local}"
            print(f"  💾 Enregistrée : /{chemin_local} ({source})")
        else:
            print(f"  ⚠️ Échec téléchargement vers {chemin_local} — URL externe conservée")

    return img

def telecharger_image(url, chemin_local, timeout=30):
    """Télécharge une image depuis une URL distante vers un chemin local.
    Crée les dossiers parents si nécessaire. Retourne True en cas de succès.

    Après téléchargement réussi, génère automatiquement les 3 variantes
    responsive (400/800/1200) via Pillow.
    """
    try:
        p = Path(chemin_local)
        p.parent.mkdir(parents=True, exist_ok=True)

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()

        if len(data) < 5000:  # trop petit = probablement une erreur
            print(f"  ⚠️ Image suspecte (taille {len(data)}o) : {url[:80]}")
            return False

        p.write_bytes(data)

        # Génération automatique des 3 variantes responsive
        # (pour servir la bonne taille sur mobile/tablet/desktop)
        generer_variantes(chemin_local)

        return True
    except Exception as e:
        print(f"  ⚠️ Erreur téléchargement image : {e}")
        return False

# ─── CLAUDE API ───────────────────────────────────────────
def appeler_claude(prompt, max_tokens=3000):
    client  = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()

def extraire_balise(texte, balise):
    """Extrait le contenu entre <BALISE>...</BALISE>.
    Tolère la balise fermante manquante (fin de texte tronqué) :
    dans ce cas on prend depuis <BALISE> jusqu'à la prochaine balise de même format
    ou jusqu'à la fin du texte."""
    # Cas normal
    m = re.search(f"<{balise}>(.*?)</{balise}>", texte, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Cas troncature : balise ouvrante présente, fermante manquante
    m = re.search(f"<{balise}>(.*?)(?=<[A-Z]+\\d*[QRA]?>|$)", texte, re.DOTALL)
    if m:
        return m.group(1).strip()
    return ""

def nettoyer_markdown_vers_html(texte):
    """Convertit le Markdown résiduel en HTML (cas où Claude ignore la consigne HTML).
    - **gras** → <strong>gras</strong>
    - *italique* → <em>italique</em>
    - ## Titre → <h2>Titre</h2>
    - ### Titre → <h3>Titre</h3>
    - Liste - item → <ul><li>item</li></ul>
    """
    if not texte:
        return ""
    lignes = texte.split('\n')
    out = []
    in_list = False
    for ligne in lignes:
        strip = ligne.strip()
        # Titres markdown en début de ligne
        m = re.match(r'^(#{2,4})\s+(.+)$', strip)
        if m:
            if in_list:
                out.append('</ul>')
                in_list = False
            n = len(m.group(1))  # 2, 3 ou 4
            out.append(f'<h{n}>{m.group(2)}</h{n}>')
            continue
        # Listes markdown
        if re.match(r'^[-*]\s+(.+)$', strip):
            if not in_list:
                out.append('<ul>')
                in_list = True
            item = re.sub(r'^[-*]\s+', '', strip)
            out.append(f'<li>{item}</li>')
            continue
        # Fin de liste
        if in_list and not strip:
            out.append('</ul>')
            in_list = False
        out.append(ligne)
    if in_list:
        out.append('</ul>')
    html = '\n'.join(out)
    # Gras et italique inline
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', r'<em>\1</em>', html)
    # Supprimer les # résiduels en début de ligne (h1 markdown)
    html = re.sub(r'^\s*#\s+(.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    return html

def compter_mots_html(html):
    """Compte approximatif du nombre de mots dans un HTML (retire les balises)."""
    if not html:
        return 0
    texte = re.sub(r'<[^>]+>', ' ', html)
    texte = re.sub(r'\s+', ' ', texte)
    return len(texte.split())

def slugify(texte):
    s = texte.lower()
    for a, b in [('à','a'),('â','a'),('é','e'),('è','e'),('ê','e'),
                 ('î','i'),('ô','o'),('ù','u'),('û','u'),('ç','c')]:
        s = s.replace(a, b)
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'\s+', '-', s.strip())
    return re.sub(r'-+', '-', s)[:60]

# ─── SCHEMAS JSON-LD ──────────────────────────────────────
def schema_breadcrumb(items):
    """items = [{"name": "Accueil", "url": "..."}, ...]"""
    elements = []
    for i, item in enumerate(items, 1):
        elements.append({
            "@type": "ListItem",
            "position": i,
            "name": item["name"],
            "item": item["url"]
        })
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": elements
    }, ensure_ascii=False)

def schema_faq(questions_reponses):
    """questions_reponses = [{"q": "...", "r": "..."}, ...]"""
    if not questions_reponses:
        return ""
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": qr["q"],
                "acceptedAnswer": {"@type": "Answer", "text": qr["r"]}
            }
            for qr in questions_reponses
        ]
    }, ensure_ascii=False)

def schema_article(h1, meta, image_url, date_published=None, date_modified=None, word_count=None):
    """Schema Article avec auteur Person identifié (critique E-E-A-T / Discover).
    L'image pointe toujours vers la variante 1200px (exigence Discover ≥ 1200px de large)."""
    # Forcer la variante 1200 px pour JSON-LD Article.image
    image_url_abs = url_1200_pour_og(image_url)
    if image_url_abs.startswith("/"):
        image_url_abs = f"{SITE_URL}{image_url_abs}"

    data = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": h1,
        "description": meta,
        "image": image_url_abs,
        "author": {
            "@type": "Person",
            "name": AUTEUR_NOM,
            "url": f"{SITE_URL}{AUTEUR_URL}",
            "description": AUTEUR_BIO_COURTE,
        },
        "publisher": {
            "@type": "Organization",
            "name": SITE_NOM,
            "url": SITE_URL,
            "logo": {"@type": "ImageObject", "url": f"{SITE_URL}/logo.png"}
        },
        "inLanguage": "fr",
    }
    if date_published:
        data["datePublished"] = date_published
    if date_modified:
        data["dateModified"] = date_modified
    if word_count:
        data["wordCount"] = word_count
    return json.dumps(data, ensure_ascii=False)

# ─── HELPERS AUTEUR / DATES (E-E-A-T / Discover) ──────────

# Noms des mois en français (indépendant de la locale système)
MOIS_FR = [
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre"
]

def format_date_fr(date_iso):
    """Formate une date ISO (YYYY-MM-DD) en français : '21 avril 2026'.
    Indépendant de la locale système (important pour GitHub Actions en anglais)."""
    try:
        dt = datetime.strptime(date_iso, "%Y-%m-%d")
        return f"{dt.day} {MOIS_FR[dt.month]} {dt.year}"
    except Exception:
        return date_iso

def bloc_date_auteur_top(date_published, date_modified=None):
    """Bloc affiché EN HAUT de chaque article : date publication + auteur.
    C'est ce que Discover adore voir : auteur identifié + date récente."""
    date_pub_fr = format_date_fr(date_published)
    maj = ""
    if date_modified and date_modified != date_published:
        date_mod_fr = format_date_fr(date_modified)
        maj = f' • <span class="date-maj">Mis à jour le {date_mod_fr}</span>'
    # Extrait les initiales : "Mathias D." → "MD" ; "Mathias" → "M"
    parts = AUTEUR_NOM.replace(".", "").split()
    initiales = (parts[0][0] + parts[-1][0]) if len(parts) > 1 else parts[0][0]
    return (
        f'<div class="meta-article" style="display:flex;align-items:center;gap:10px;'
        f'padding:12px 0;margin:14px 0;border-top:1px solid #e8e8e0;border-bottom:1px solid #e8e8e0;'
        f'color:#555;font-size:.92rem;flex-wrap:wrap;">'
        f'<span style="display:inline-flex;align-items:center;gap:8px;">'
        f'<span style="width:34px;height:34px;border-radius:50%;background:#2d5a3d;color:#fff;'
        f'display:inline-flex;align-items:center;justify-content:center;font-weight:700;'
        f'font-size:.85rem;">{initiales}</span>'
        f'Par <a href="{AUTEUR_URL}" style="color:#2d5a3d;text-decoration:none;font-weight:600;">{AUTEUR_NOM}</a>'
        f'</span>'
        f'<span style="color:#aaa;">•</span>'
        f'<span>Publié le <time datetime="{date_published}">{date_pub_fr}</time></span>'
        f'{maj}'
        f'</div>'
    )

def bloc_auteur_fin_article():
    """Bloc bio de l'auteur affiché EN BAS de chaque article (crédibilité, E-E-A-T)."""
    parts = AUTEUR_NOM.replace(".", "").split()
    initiales = (parts[0][0] + parts[-1][0]) if len(parts) > 1 else parts[0][0]
    return (
        f'<div class="bloc-auteur" style="display:flex;gap:20px;align-items:flex-start;'
        f'background:#fafaf7;border:1px solid #e8e8e0;border-radius:10px;padding:24px;'
        f'margin:40px 0;flex-wrap:wrap;">'
        f'<div style="flex-shrink:0;width:80px;height:80px;border-radius:50%;background:#2d5a3d;'
        f'color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;'
        f'font-size:1.6rem;">{initiales}</div>'
        f'<div style="flex:1;min-width:220px;">'
        f'<div style="font-size:.85rem;color:#888;text-transform:uppercase;letter-spacing:.5px;'
        f'margin-bottom:4px;">À propos de l\'auteur</div>'
        f'<h3 style="margin:0 0 8px;color:#2d5a3d;font-family:Georgia,serif;font-size:1.15rem;">'
        f'<a href="{AUTEUR_URL}" style="color:#2d5a3d;text-decoration:none;">{AUTEUR_NOM}</a></h3>'
        f'<div style="color:#666;font-size:.88rem;margin-bottom:8px;">{AUTEUR_ROLE}</div>'
        f'<p style="margin:0;color:#444;line-height:1.6;font-size:.95rem;">{AUTEUR_BIO_COURTE}</p>'
        f'</div></div>'
    )

def generer_page_a_propos(archi):
    """Génère la page /a-propos.html avec la présentation de l'auteur Mathias D.
    Critique pour E-E-A-T : Google Discover regarde cette page pour valider la crédibilité."""
    page_url = f"{SITE_URL}/a-propos.html"
    breadcrumb = schema_breadcrumb([
        {"name": "Accueil", "url": f"{SITE_URL}/"},
        {"name": "À propos", "url": page_url}
    ])
    # Schema Person pour l'auteur (plus fort E-E-A-T qu'Organization)
    schema_person = json.dumps({
        "@context": "https://schema.org",
        "@type": "Person",
        "name": AUTEUR_NOM,
        "jobTitle": AUTEUR_ROLE,
        "description": AUTEUR_BIO_COURTE,
        "url": page_url,
        "worksFor": {"@type": "Organization", "name": SITE_NOM, "url": SITE_URL},
        "email": "contact@eoliz.fr",
    }, ensure_ascii=False)

    parts = AUTEUR_NOM.replace(".", "").split()
    initiales = (parts[0][0] + parts[-1][0]) if len(parts) > 1 else parts[0][0]

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>À propos — {AUTEUR_NOM} | {SITE_NOM}</title>
  <meta name="description" content="Découvrez {AUTEUR_NOM}, {AUTEUR_ROLE}. Sa méthode éditoriale, ses engagements et sa vision pour vous aider à choisir la pergola idéale.">
  {meta_commune()}
  {meta_sociales(
    titre=f"À propos — {AUTEUR_NOM} | {SITE_NOM}",
    description=f"Découvrez {AUTEUR_NOM}, {AUTEUR_ROLE}. Sa méthode éditoriale, ses engagements et sa vision.",
    image_url="/images/home/slider-1.webp",
    url_page=page_url,
    type_og="profile"
  )}
  <link rel="canonical" href="{page_url}">
  {lien_css()}
  <style>
    .apropos{{max-width:820px;margin:40px auto;padding:0 20px;}}
    .apropos-hero{{display:flex;gap:30px;align-items:center;margin-bottom:40px;flex-wrap:wrap;}}
    .apropos-avatar{{width:120px;height:120px;border-radius:50%;background:#2d5a3d;color:#fff;
      display:flex;align-items:center;justify-content:center;font-weight:700;font-size:2.5rem;flex-shrink:0;}}
    .apropos-nom{{font-family:Georgia,serif;color:#2d5a3d;font-size:2rem;margin:0 0 6px;}}
    .apropos-role{{color:#666;font-size:1.05rem;margin:0;}}
    .apropos-section{{margin:30px 0;line-height:1.75;color:#333;}}
    .apropos-section h2{{font-family:Georgia,serif;color:#2d5a3d;font-size:1.4rem;margin:30px 0 14px;
      padding-bottom:8px;border-bottom:2px solid #e8e8e0;}}
    .apropos-section p{{margin:0 0 14px;}}
    .apropos-section ul{{padding-left:22px;}}
    .apropos-section li{{margin-bottom:8px;}}
    .apropos-section strong{{color:#2d5a3d;}}
  </style>
  <script type="application/ld+json">{breadcrumb}</script>
  <script type="application/ld+json">{schema_person}</script>
</head>
<body>
  {construire_header(archi, "racine")}
  <main class="apropos">
    <nav class="fil-ariane"><a href="/">Accueil</a> › <span>À propos</span></nav>

    <div class="apropos-hero">
      <div class="apropos-avatar">{initiales}</div>
      <div>
        <h1 class="apropos-nom">{AUTEUR_NOM}</h1>
        <p class="apropos-role">{AUTEUR_ROLE}</p>
      </div>
    </div>

    <div class="apropos-section">
      <h2>Qui suis-je ?</h2>
      <p>Bienvenue sur <strong>{SITE_NOM}</strong>. Je suis <strong>{AUTEUR_NOM}</strong>, rédacteur en chef de ce site. Passionné d'aménagement extérieur et plus particulièrement de pergolas, j'ai créé ce site pour centraliser toutes les informations utiles aux propriétaires français qui envisagent d'installer une pergola chez eux.</p>
      <p>Mon objectif est simple : vous donner accès à une information <strong>fiable, actualisée et pratique</strong>, loin du discours commercial des fabricants et des comparateurs qui multiplient les liens d'affiliation au détriment de la qualité éditoriale.</p>

      <h2>Pourquoi ce site ?</h2>
      <p>Quand j'ai moi-même cherché à installer une pergola chez des proches, je me suis heurté à un constat frustrant : les informations disponibles sur internet étaient soit <em>trop commerciales</em> (catalogues fabricants), soit <em>trop superficielles</em> (blogs génériques qui recopient les mêmes contenus), soit <em>dépassées</em> (prix datés, normes obsolètes).</p>
      <p>J'ai donc décidé de construire une ressource complète qui couvre :</p>
      <ul>
        <li>Les <strong>prix réels du marché français 2025-2026</strong>, avec des fourchettes précises par matériau et dimension</li>
        <li>Les <strong>démarches administratives</strong> (permis de construire, déclaration préalable) expliquées simplement</li>
        <li>Les <strong>critères techniques</strong> pour choisir la bonne pergola selon votre projet et votre budget</li>
        <li>Les <strong>pièges à éviter</strong> lors de l'achat et de l'installation</li>
        <li>Un <strong>blog mis à jour régulièrement</strong> avec des actualités et des cas pratiques</li>
      </ul>

      <h2>Ma méthode de travail</h2>
      <p>Chaque contenu publié sur {SITE_NOM} est construit avec rigueur :</p>
      <ul>
        <li>Consultation systématique des <strong>sources officielles</strong> : service-public.fr, ADEME, normes AFNOR, code de l'urbanisme</li>
        <li>Analyse des <strong>catalogues des fabricants français</strong> (tarifs pratiqués, matériaux, garanties, délais)</li>
        <li>Recoupement avec des <strong>retours d'expérience</strong> de propriétaires et d'installateurs</li>
        <li>Relecture et mise à jour au moins <strong>annuelle</strong> pour garantir la pertinence des prix et des normes</li>
      </ul>
      <p>Je m'appuie également sur des outils d'intelligence artificielle comme <em>support de rédaction</em>, pour garantir une couverture exhaustive des sujets. Mais chaque contenu est <strong>relu, vérifié et enrichi</strong> pour coller à la réalité du terrain français.</p>

      <h2>Mes engagements</h2>
      <ul>
        <li><strong>Indépendance</strong> : je ne suis affilié à aucun fabricant ni à aucune enseigne.</li>
        <li><strong>Transparence</strong> : lorsqu'un contenu est sponsorisé, il est clairement identifié comme tel.</li>
        <li><strong>Fiabilité</strong> : je préfère attendre d'avoir vérifié une information plutôt que de publier une donnée incertaine.</li>
        <li><strong>Accessibilité</strong> : les guides sont gratuits, sans mur payant, et conçus pour être lus par tous.</li>
      </ul>

      <h2>Éditeur du site</h2>
      <p>{SITE_NOM} est édité par <strong>EOLIZ</strong>, structure dédiée à la création de sites de référence sur l'habitat et l'aménagement extérieur. Pour les informations administratives, consultez nos <a href="/mentions-legales.html">mentions légales</a>.</p>

      <h2>Me contacter</h2>
      <p>Pour toute question, remarque, suggestion de sujet ou demande de partenariat, écrivez-moi à <a href="mailto:contact@eoliz.fr">contact@eoliz.fr</a>. Je réponds personnellement à tous les mails dans un délai raisonnable.</p>
    </div>
  </main>
  {construire_footer("racine")}
  {lien_js()}
  {banner_cookies()}
</body></html>"""
    Path("a-propos.html").write_text(html, encoding="utf-8")
    print("✅ a-propos.html")

def schema_howto(titre, etapes):
    """Pour pages installation."""
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "HowTo",
        "name": titre,
        "step": [
            {"@type": "HowToStep", "name": e["nom"], "text": e["texte"]}
            for e in etapes
        ]
    }, ensure_ascii=False)

# ─── SCHEMAS GLOBAUX (ajoutés uniquement sur la home) ────
def schema_website():
    """Schema WebSite avec SearchAction : permet à Google d'afficher
    une search box directe dans les résultats si la requête contient le nom du site.
    À mettre UNIQUEMENT sur la home."""
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "WebSite",
        "url": f"{SITE_URL}/",
        "name": SITE_NOM,
        "description": SITE_DESCRIPTION_COURTE,
        "inLanguage": "fr-FR",
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"{SITE_URL}/?q={{search_term_string}}"
            },
            "query-input": "required name=search_term_string"
        }
    }, ensure_ascii=False)

def schema_organization():
    """Schema Organization (sitewide) : ancre l'entité dans le Knowledge Graph.
    À mettre UNIQUEMENT sur la home."""
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": SITE_NOM,
        "url": SITE_URL,
        "logo": {
            "@type": "ImageObject",
            "url": f"{SITE_URL}/logo.png",
            "width": 512,
            "height": 512
        },
        "description": SITE_DESCRIPTION_COURTE,
        "email": "contact@eoliz.fr",
        "publishingPrinciples": f"{SITE_URL}/a-propos.html",
        "sameAs": []  # Ajouter ici les URLs des réseaux sociaux si tu en créées plus tard
    }, ensure_ascii=False)

def schema_itemlist_piliers(archi):
    """Schema ItemList pour les 9 piliers sur la home.
    Aide Google à comprendre que la home présente une liste structurée."""
    items = []
    for idx, pilier in enumerate(archi["piliers"], start=1):
        items.append({
            "@type": "ListItem",
            "position": idx,
            "name": pilier["titre"],
            "url": f"{SITE_URL}/{pilier['slug']}.html"
        })
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": f"Guides thématiques {SITE_NOM}",
        "itemListElement": items
    }, ensure_ascii=False)


# ─── ARTICLES SIMILAIRES ──────────────────────────────────
def generer_articles_similaires(slug_actuel, pilier_id, articles, n=6):
    """Articles similaires en bas des pages blog : titre cliquable + visuel en dessous.
    Format identique au maillage des pages secondaires (cohérence visuelle)."""
    similaires = [
        a for a in articles
        if a.get("pilier_id") == pilier_id and a.get("slug") != slug_actuel
    ][:n]

    if not similaires:
        return ""

    html = '<section class="maillage-articles"><h2>À lire aussi dans la même thématique</h2><div class="maillage-grid">'
    for art in similaires:
        thumb = art.get("thumb", "")
        # Si pas de thumb, placeholder (rare)
        img_src = thumb if thumb else "/images/home/slider-1.webp"
        img_maillage = img_responsive(img_src, art['titre'], role="thumb",
                                      loading="lazy", classe="maillage-img")
        html += f'''
        <div class="maillage-card">
          <a href="/blog/{art['slug']}.html" class="maillage-titre">{art['titre']}</a>
          <a href="/blog/{art['slug']}.html" class="maillage-img-link">
            {img_maillage}
          </a>
        </div>'''
    html += '</div></section>'
    return html

# ─── MAILLAGE BLOG → SECONDAIRES (statique) ───────────────
def generer_liens_blog_sur_secondaire(pilier_id, secondaire_slug, articles, n=9):
    """Articles liés affichés sur la page secondaire en bas : titre cliquable + visuel.
    Même format que le maillage vers autres secondaires (cohérence visuelle).
    n=9 par défaut (3 rangées de 3 sur desktop grand écran) pour enrichir le maillage."""
    lies = [
        a for a in articles
        if a.get("pilier_id") == pilier_id
        and secondaire_slug in a.get("secondaire_slug", "")
    ][:n]

    if not lies:
        # Fallback : articles du même pilier
        lies = [a for a in articles if a.get("pilier_id") == pilier_id][:n]

    if not lies:
        return ""

    html = '<div class="maillage-grid">'
    for art in lies:
        thumb = art.get("thumb", "")
        img_src = thumb if thumb else "/images/home/slider-1.webp"
        img_maillage = img_responsive(img_src, art['titre'], role="thumb",
                                      loading="lazy", classe="maillage-img")
        html += f'''
        <div class="maillage-card">
          <a href="/blog/{art['slug']}.html" class="maillage-titre">{art['titre']}</a>
          <a href="/blog/{art['slug']}.html" class="maillage-img-link">
            {img_maillage}
          </a>
        </div>'''
    html += '</div>'
    return html

# ─── HEADER / FOOTER ──────────────────────────────────────
# Les liens de navigation utilisent des CHEMINS ABSOLUS (commençant par /).
# C'est le standard sur GitHub Pages avec domaine custom : la racine "/" pointe
# toujours vers la racine du site, peu importe la profondeur de la page courante.
# Cela évite tous les bugs de chemins relatifs (../../) qui cassent à la moindre
# modification de structure.
def construire_header(archi, niveau="racine", pilier_actuel=None):
    """Construit le header avec des liens absolus (robustes quelle que soit la profondeur)."""
    menus = ""
    PILIERS_MENU = ["bioclimatique", "bois", "aluminium", "prix", "installation"]
    for p in [p for p in archi["piliers"] if p["id"] in PILIERS_MENU]:
        actif = "active" if pilier_actuel and p["id"] == pilier_actuel else ""
        # Chemins absolus — valides depuis n'importe quelle profondeur
        lien_pilier = f"/{p['slug']}.html"

        sous_liens = "".join(
            f'<a href="/{p["id"]}/{s["slug"]}.html">{s["titre"]}</a>\n'
            for s in p["secondaires"]
        )
        menus += f"""
        <div class="menu-item {actif}">
          <a href="{lien_pilier}" class="menu-pilier">{p['titre']}</a>
          <div class="sous-menu">{sous_liens}</div>
        </div>"""

    return f"""<header>
  <div class="container header-inner">
    <a href="/" class="logo">{SITE_LOGO}</a>
    <button class="menu-toggle" onclick="toggleMenu()">☰</button>
    <nav id="main-nav">
      <a href="/">Accueil</a>
      <div class="menu-deroulant">{menus}</div>
      <a href="/blog.html">Blog</a>
    </nav>
  </div>
</header>"""

def construire_footer(niveau="racine"):
    """Footer avec liens absolus — enrichi pour E-E-A-T et Discover."""
    annee = datetime.now().year
    return f"""<footer>
  <div class="container">
    <p style="margin:0 0 8px;">© {annee} EOLIZ — {SITE_NOM}</p>
    <p style="margin:0;font-size:.9rem;">
      <a href="/a-propos.html">À propos</a> •
      <a href="/mentions-legales.html">Mentions légales</a> •
      <a href="/politique-de-confidentialite.html">Confidentialité</a> •
      <a href="/cookies.html">Cookies</a> •
      <a href="/feed.xml">Flux RSS</a>
    </p>
  </div>
</footer>"""

def meta_commune():
    """Balises meta communes à toutes les pages (robots, GSC, AdSense, GA4, RSS, CSS logo).
    Inclut les preconnects vers les domaines tiers pour accélérer les connexions (Core Web Vitals)."""
    parts = [
        '<meta name="robots" content="max-image-preview:large">',
        # Preconnects vers domaines tiers critiques (gagne ~200-500ms sur LCP)
        '  <link rel="preconnect" href="https://www.googletagmanager.com" crossorigin>',
        '  <link rel="preconnect" href="https://pagead2.googlesyndication.com" crossorigin>',
        '  <link rel="dns-prefetch" href="https://www.google-analytics.com">',
        '  ' + balise_gsc(),
        '  ' + script_adsense_head(),
        '  ' + script_ga4_head(),
        f'  <link rel="alternate" type="application/rss+xml" title="{SITE_NOM} — Articles" href="{SITE_URL}/feed.xml">',
        '  ' + css_logo(),
    ]
    return '\n  '.join(parts)

def css_logo():
    """CSS du logo magazine 'Pergola / GUIDE' — adapté au fond vert foncé du header.
    Palette blanc + doré pour un maximum de lisibilité et un look premium."""
    return '''<style>
    .logo{display:inline-flex;align-items:baseline;gap:10px;text-decoration:none;
      font-family:Georgia,"Times New Roman",serif;line-height:1;padding:6px 0;white-space:nowrap;}
    .logo-pergola{font-size:1.5rem;font-weight:400;color:#ffffff;
      font-style:italic;letter-spacing:.2px;}
    .logo-slash{font-size:1.1rem;color:#c5a572;font-weight:300;
      position:relative;top:-2px;opacity:.85;}
    .logo-guide{font-size:.95rem;font-weight:500;color:#ffffff;
      letter-spacing:4px;text-transform:uppercase;}
    .logo:hover .logo-slash{opacity:1;}
    @media (max-width:640px){
      .logo{gap:7px;}
      .logo-pergola{font-size:1.22rem;}
      .logo-slash{font-size:.9rem;}
      .logo-guide{font-size:.82rem;letter-spacing:3px;}
    }
  </style>'''

def meta_sociales(titre, description, image_url, url_page, type_og="article"):
    """Génère les balises OpenGraph (Facebook/LinkedIn/WhatsApp) + Twitter Cards.
    Ces balises contrôlent le rendu des previews lors du partage sur réseaux sociaux.

    Args:
        titre       : Titre affiché dans le preview
        description : Description affichée sous le titre (max ~160 car.)
        image_url   : URL ABSOLUE de l'image (1200x630 recommandé)
        url_page    : URL canonique de la page
        type_og     : 'article' pour contenus éditoriaux, 'website' pour home
    """
    # Forcer la variante 1200px pour og:image (exigence Google Discover).
    # Pour une URL locale /images/blog/x.webp, on pointe vers x-1200.webp
    # Pour une URL externe, on la garde telle quelle.
    image_url = url_1200_pour_og(image_url)
    # S'assurer que l'image est en URL absolue (pas /images/... mais https://...)
    if image_url.startswith("/"):
        image_url = f"{SITE_URL}{image_url}"
    # Si url_page est relative, la rendre absolue
    if url_page.startswith("/"):
        url_page = f"{SITE_URL}{url_page}"
    # Échapper les guillemets dans titre/description pour éviter de casser l'HTML
    titre_safe = titre.replace('"', '&quot;')
    desc_safe  = description.replace('"', '&quot;')

    return (
        f'<!-- OpenGraph (Facebook, LinkedIn, WhatsApp, Discord, Slack) -->\n'
        f'  <meta property="og:type" content="{type_og}">\n'
        f'  <meta property="og:site_name" content="{SITE_NOM}">\n'
        f'  <meta property="og:locale" content="fr_FR">\n'
        f'  <meta property="og:title" content="{titre_safe}">\n'
        f'  <meta property="og:description" content="{desc_safe}">\n'
        f'  <meta property="og:url" content="{url_page}">\n'
        f'  <meta property="og:image" content="{image_url}">\n'
        f'  <meta property="og:image:width" content="1200">\n'
        f'  <meta property="og:image:height" content="630">\n'
        f'  <meta property="og:image:alt" content="{titre_safe}">\n'
        f'  <!-- Twitter Cards -->\n'
        f'  <meta name="twitter:card" content="summary_large_image">\n'
        f'  <meta name="twitter:title" content="{titre_safe}">\n'
        f'  <meta name="twitter:description" content="{desc_safe}">\n'
        f'  <meta name="twitter:image" content="{image_url}">\n'
        f'  <meta name="twitter:image:alt" content="{titre_safe}">'
    )

# ─── BANNER COOKIES RGPD ──────────────────────────────────
# HTML + CSS + JS autonomes, injectés juste avant </body> sur chaque page.
# Stocke le consentement dans localStorage et met à jour GA4 Consent Mode.
def banner_cookies():
    return '''
<!-- Banner cookies RGPD (CNIL-compliant) -->
<div id="pg-cookie-banner" style="display:none;position:fixed;bottom:0;left:0;right:0;
  background:#fff;border-top:1px solid #e0e0e0;box-shadow:0 -4px 20px rgba(0,0,0,.1);
  padding:22px 24px;z-index:9999;font-family:system-ui,Arial,sans-serif;">
  <div style="max-width:1200px;margin:0 auto;display:flex;gap:20px;align-items:center;flex-wrap:wrap;">
    <div style="flex:1;min-width:260px;">
      <strong style="display:block;margin-bottom:4px;color:#2d5a3d;">🍪 Gestion des cookies</strong>
      <span style="font-size:.9rem;color:#555;">
        Nous utilisons des cookies pour mesurer l'audience (Google Analytics) et afficher des publicités pertinentes.
        Vous pouvez accepter, refuser ou personnaliser votre choix à tout moment.
        <a href="/cookies.html" style="color:#2d5a3d;">En savoir plus</a>
      </span>
    </div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;">
      <button onclick="pgConsent.refuse()" style="padding:10px 16px;background:#f5f5f5;border:1px solid #ddd;
        border-radius:6px;cursor:pointer;font-size:.9rem;">Tout refuser</button>
      <button onclick="pgConsent.personalize()" style="padding:10px 16px;background:#f5f5f5;border:1px solid #ddd;
        border-radius:6px;cursor:pointer;font-size:.9rem;">Personnaliser</button>
      <button onclick="pgConsent.accept()" style="padding:10px 18px;background:#2d5a3d;color:#fff;border:none;
        border-radius:6px;cursor:pointer;font-size:.9rem;font-weight:600;">Tout accepter</button>
    </div>
  </div>
</div>

<!-- Modal personnalisation -->
<div id="pg-cookie-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:10000;
  align-items:center;justify-content:center;padding:20px;">
  <div style="background:#fff;border-radius:10px;max-width:500px;width:100%;padding:28px;
    font-family:system-ui,Arial,sans-serif;">
    <h2 style="margin:0 0 14px;color:#2d5a3d;">Préférences cookies</h2>
    <p style="color:#555;font-size:.9rem;margin:0 0 20px;">
      Choisissez les catégories de cookies que vous acceptez.
    </p>
    <label style="display:flex;align-items:center;gap:10px;padding:10px;background:#f5f5f5;border-radius:6px;margin-bottom:8px;">
      <input type="checkbox" checked disabled>
      <div><strong>Essentiels</strong><br><span style="font-size:.85rem;color:#666;">Toujours actifs (navigation).</span></div>
    </label>
    <label style="display:flex;align-items:center;gap:10px;padding:10px;border:1px solid #e0e0e0;border-radius:6px;margin-bottom:8px;cursor:pointer;">
      <input type="checkbox" id="pg-c-analytics">
      <div><strong>Mesure d'audience</strong><br><span style="font-size:.85rem;color:#666;">Google Analytics (anonymisé).</span></div>
    </label>
    <label style="display:flex;align-items:center;gap:10px;padding:10px;border:1px solid #e0e0e0;border-radius:6px;margin-bottom:20px;cursor:pointer;">
      <input type="checkbox" id="pg-c-ads">
      <div><strong>Publicité personnalisée</strong><br><span style="font-size:.85rem;color:#666;">AdSense avec annonces ciblées.</span></div>
    </label>
    <div style="display:flex;gap:10px;justify-content:flex-end;">
      <button onclick="document.getElementById('pg-cookie-modal').style.display='none';" style="padding:10px 16px;background:#f5f5f5;border:1px solid #ddd;border-radius:6px;cursor:pointer;">Annuler</button>
      <button onclick="pgConsent.savePersonalized()" style="padding:10px 18px;background:#2d5a3d;color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:600;">Enregistrer</button>
    </div>
  </div>
</div>

<script>
  (function(){
    var STORAGE_KEY = 'pg_consent';
    var banner = document.getElementById('pg-cookie-banner');
    var modal  = document.getElementById('pg-cookie-modal');
    function saved(){ try{return JSON.parse(localStorage.getItem(STORAGE_KEY));}catch(e){return null;} }
    function apply(c){
      if (typeof gtag === 'function') {
        gtag('consent', 'update', {
          'ad_storage': c.ads ? 'granted' : 'denied',
          'ad_user_data': c.ads ? 'granted' : 'denied',
          'ad_personalization': c.ads ? 'granted' : 'denied',
          'analytics_storage': c.analytics ? 'granted' : 'denied'
        });
      }
    }
    function save(c){
      c.ts = Date.now();
      localStorage.setItem(STORAGE_KEY, JSON.stringify(c));
      apply(c);
      banner.style.display = 'none';
      modal.style.display  = 'none';
    }
    window.pgConsent = {
      accept:  function(){ save({analytics:true,  ads:true}); },
      refuse:  function(){ save({analytics:false, ads:false}); },
      personalize: function(){ modal.style.display = 'flex'; },
      savePersonalized: function(){
        save({
          analytics: document.getElementById('pg-c-analytics').checked,
          ads:       document.getElementById('pg-c-ads').checked
        });
      },
      reset: function(){ localStorage.removeItem(STORAGE_KEY); location.reload(); }
    };
    if (!saved()) { banner.style.display = 'block'; }
    else { apply(saved()); }
  })();
</script>
'''

# ─── CHEMINS CSS / JS ─────────────────────────────────────
# Avec des liens absolus pour les assets, plus besoin de gérer la profondeur.
def lien_css():
    return '<link rel="stylesheet" href="/style.css">'

def lien_js():
    # defer = non bloquant, téléchargé en parallèle, exécuté après le parsing HTML
    return '<script src="/main.js" defer></script>'

def _preload_responsive(url_image, role="hero"):
    """Génère un <link rel="preload"> responsive pour l'image LCP.

    Utilise imagesrcset + imagesizes pour que le navigateur preload
    la bonne taille selon l'écran (gain crucial sur LCP mobile).

    Si l'image est externe (Unsplash/Replicate), fallback preload simple.
    """
    from image_utils import est_image_locale, url_variante, SIZES_PAR_ROLE

    if not est_image_locale(url_image):
        return f'<link rel="preload" as="image" href="{url_image}" fetchpriority="high">'

    url_400  = url_variante(url_image, 400)
    url_800  = url_variante(url_image, 800)
    url_1200 = url_variante(url_image, 1200)
    sizes = SIZES_PAR_ROLE.get(role, SIZES_PAR_ROLE["default"])

    return (
        f'<link rel="preload" as="image" href="{url_800}" '
        f'imagesrcset="{url_400} 400w, {url_800} 800w, {url_1200} 1200w" '
        f'imagesizes="{sizes}" '
        f'fetchpriority="high">'
    )

# ─── PAGE D'ACCUEIL ───────────────────────────────────────
def generer_accueil(archi, articles=None, regenerer_images=False):
    """Page d'accueil avec slider, intro fixe, encarts AdSense et derniers articles statiques.

    regenerer_images=True  : force la régénération des 3 images du slider (mode full)
    regenerer_images=False : réutilise les images existantes dans images/home/ si présentes
                             (mode blog quotidien — évite 3 appels Replicate coûteux)
    """
    print("🏠 Génération page d'accueil...")
    articles = articles or []

    # ─── 3 images du slider ─────────────────────────────────────
    # get_image() gère automatiquement le cache via chemin_local :
    # - si le fichier existe déjà localement → réutilisé (0 appel Replicate)
    # - sinon → génération Replicate + téléchargement local
    # regenerer_images=True force une nouvelle génération en supprimant les fichiers
    if regenerer_images:
        for i in range(1, 4):
            f = Path(f"images/home/slider-{i}.webp")
            if f.exists():
                f.unlink()
        print("  🗑️ Anciennes images slider supprimées (regenerer_images=True)")

    img_slider_1 = get_image("modern bioclimatic pergola with adjustable aluminum louvers over contemporary terrace, outdoor dining area, Mediterranean evening ambiance",
                             modele="dev", chemin_local="images/home/slider-1.webp")
    img_slider_2 = get_image("sleek white aluminum pergola on modern rooftop terrace with city view, minimalist architecture, golden hour lighting",
                             modele="dev", chemin_local="images/home/slider-2.webp")
    img_slider_3 = get_image("elegant wooden pergola with climbing wisteria flowers in lush provencal garden, stone terrace, french countryside",
                             modele="dev", chemin_local="images/home/slider-3.webp")
    slider_urls = [img_slider_1["url"], img_slider_2["url"], img_slider_3["url"]]

    slides_html = ""
    for idx, url in enumerate(slider_urls, start=1):
        # Slide avec <img srcset> au lieu de background-image CSS :
        # permet au navigateur de choisir la bonne taille selon l'écran
        # (400px sur mobile, 1200px sur desktop) → LCP massivement amélioré
        loading_attr = "eager" if idx == 1 else "lazy"
        fp_attr = "high" if idx == 1 else None
        img_slide = img_responsive(
            url, f"Pergola — image {idx}",
            role="hero",
            loading=loading_attr,
            fetchpriority=fp_attr,
            width=1200, height=520,
            classe="home-slide-img"
        )
        slides_html += f'''
      <div class="home-slide home-slide-{idx}">
        {img_slide}
        <div class="home-slide-overlay"></div>
      </div>'''

    # ─── Cards piliers (avec miniatures) ────────────────────────
    # Chaque card affiche l'image /images/piliers/{slug}-1.webp (générée par le build full)
    cards = ""
    for p in archi["piliers"]:
        img_path = f"/images/piliers/{p['slug']}-1.webp"
        img_card_html = img_responsive(img_path, p['titre'], role="card",
                                        loading="lazy", classe="pilier-card-img")
        cards += f'''
    <a href="/{p['slug']}.html" class="pilier-card">
      {img_card_html}
      <div class="pilier-card-body">
        <h2>{p['titre']}</h2>
        <p>{p['description']}</p>
        <span class="voir-plus">Lire la suite →</span>
      </div>
    </a>'''

    # ─── Derniers articles en HTML statique (avec miniatures) ───
    derniers_cards = ""
    if articles:
        for art in articles[:6]:  # 6 derniers articles
            thumb = art.get("thumb", "")
            img_html = (
                img_responsive(thumb, art["titre"], role="card",
                               loading="lazy", classe="card-image")
                if thumb else
                '<div class="card-image card-image-placeholder">📄</div>'
            )
            description = art.get('description', '')[:100]
            derniers_cards += f"""
    <a href="/blog/{art['slug']}.html" class="article-card">
      {img_html}
      <div class="card-body">
        <span class="categorie">{art.get('categorie','Blog')}</span>
        <h3>{art['titre']}</h3>
        <p>{description}...</p>
      </div>
    </a>"""
    else:
        derniers_cards = '<p class="no-articles">Les premiers articles arrivent bientôt !</p>'

    # ─── CSS dédié à la home (inline pour ne pas toucher style.css) ─
    css_home = """
  <style>
    /* ═══ SLIDER ACCUEIL (inchangé) ════════════════════════════ */
    .home-slider{position:relative;width:100%;height:520px;overflow:hidden;margin:0;}
    .home-slide{position:absolute;top:0;left:0;width:100%;height:100%;
      opacity:0;animation:homeSlide 15s infinite;overflow:hidden;}
    .home-slide-img{position:absolute;top:0;left:0;width:100%;height:100%;
      object-fit:cover;object-position:center;display:block;}
    .home-slide-1{animation-delay:0s;}
    .home-slide-2{animation-delay:5s;}
    .home-slide-3{animation-delay:10s;}
    .home-slide-overlay{position:absolute;inset:0;
      background:linear-gradient(to bottom,rgba(0,0,0,.15) 0%,rgba(0,0,0,.55) 100%);}
    @keyframes homeSlide{
      0%,26%{opacity:0;}
      4%,22%{opacity:1;}
    }
    .home-slider-content{position:absolute;inset:0;display:flex;flex-direction:column;
      align-items:center;justify-content:center;text-align:center;color:#fff;
      padding:20px;z-index:2;}
    .home-slider-content h1{font-family:Georgia,serif;font-size:clamp(1.8rem,4vw,3rem);
      margin:0 0 16px;text-shadow:0 2px 8px rgba(0,0,0,.6);max-width:900px;}
    .home-slider-content p{font-size:clamp(1rem,1.5vw,1.25rem);margin:0;
      text-shadow:0 1px 4px rgba(0,0,0,.6);max-width:700px;}
    @media (max-width:768px){.home-slider{height:380px;}}

    /* ═══ INTRO : image à gauche (large) + texte justifié à droite ═════ */
    .home-intro{background:#fafaf7;padding:60px 0;border-bottom:1px solid #e8e8e0;}
    .home-intro-inner{max-width:1100px;margin:0 auto;padding:0 20px;
      display:grid;grid-template-columns:1.3fr 1fr;gap:40px;align-items:center;}
    .home-intro-img{width:100%;height:100%;min-height:320px;object-fit:cover;
      border-radius:10px;display:block;box-shadow:0 10px 30px rgba(45,90,61,.12);}
    .home-intro-texte h2{font-family:Georgia,serif;color:var(--vert,#2d5a3d);
      font-size:1.8rem;margin:0 0 18px;}
    .home-intro-texte p{font-size:1.02rem;line-height:1.75;color:#444;
      margin:0 0 14px;text-align:justify;}
    .home-intro-texte p:last-child{margin-bottom:0;}
    @media (max-width:768px){
      .home-intro-inner{grid-template-columns:1fr;gap:24px;}
      .home-intro-img{min-height:220px;}
    }

    /* ═══ SECTIONS ═════════════════════════════════════════════ */
    .home-section{padding:50px 0;}
    .home-section-alt{background:#fafaf7;}
    .home-section h2.section-titre{font-family:Georgia,serif;color:var(--vert,#2d5a3d);
      font-size:1.8rem;text-align:center;margin:0 0 34px;}

    /* ═══ CARDS PILIERS AVEC MINIATURES ════════════════════════ */
    .piliers-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
      gap:24px;max-width:1200px;margin:0 auto;padding:0 20px;}
    .pilier-card{background:#fff;border-radius:10px;overflow:hidden;text-decoration:none;
      color:inherit;box-shadow:0 2px 10px rgba(0,0,0,.06);
      transition:transform .25s,box-shadow .25s;display:flex;flex-direction:column;
      border:1px solid #e8e8e0;}
    .pilier-card:hover{transform:translateY(-4px);box-shadow:0 12px 32px rgba(45,90,61,.18);}
    .pilier-card-img{width:100%;height:160px;object-fit:cover;display:block;background:#f0ede5;}
    .pilier-card-body{padding:20px;flex:1;display:flex;flex-direction:column;}
    .pilier-card-body h2{font-family:Georgia,serif;color:var(--vert,#2d5a3d);
      font-size:1.25rem;margin:0 0 10px;}
    .pilier-card-body p{color:#555;font-size:.95rem;line-height:1.55;margin:0 0 14px;flex:1;}
    .pilier-card .voir-plus{color:var(--vert,#2d5a3d);font-weight:600;font-size:.9rem;}

    /* ═══ CONFIANCE (3 avantages) ══════════════════════════════ */
    .confiance-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
      gap:28px;max-width:1000px;margin:0 auto;}
    .confiance-item{text-align:center;padding:20px;}
    .confiance-item .icone{font-size:2.5rem;margin-bottom:12px;display:block;}
    .confiance-item h3{font-family:Georgia,serif;color:var(--vert,#2d5a3d);
      font-size:1.15rem;margin:0 0 8px;}
    .confiance-item p{color:#555;font-size:.95rem;line-height:1.5;margin:0;}

    /* ═══ PLACEHOLDER VIGNETTE ARTICLE SANS IMAGE ══════════════ */
    .card-image-placeholder{display:flex;align-items:center;justify-content:center;
      font-size:2.5rem;background:#f0ede5;color:#a8a397;height:180px;}
    .no-articles{text-align:center;color:#888;padding:40px 0;}
  </style>"""

    # ─── Assemblage final ──────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{SITE_NOM} — Guide complet pergolas France</title>
  <meta name="description" content="Le guide de référence sur les pergolas en France. Prix, matériaux, installation, réglementation : tout pour choisir la pergola idéale.">
  {meta_commune()}
  {meta_sociales(
    titre=f"{SITE_NOM} — Guide complet pergolas France",
    description="Le guide de référence sur les pergolas en France. Prix, matériaux, installation, réglementation : tout pour choisir la pergola idéale.",
    image_url=img_slider_1["url"],
    url_page=f"{SITE_URL}/",
    type_og="website"
  )}
  <link rel="canonical" href="{SITE_URL}/">
  <!-- Preload de l'image LCP responsive : le navigateur télécharge la bonne taille selon l'écran -->
  {_preload_responsive("/images/home/slider-1.webp", role="hero")}
  {lien_css()}
{css_home}
  <script type="application/ld+json">{schema_website()}</script>
  <script type="application/ld+json">{schema_organization()}</script>
  <script type="application/ld+json">{schema_itemlist_piliers(archi)}</script>
</head>
<body>
  {construire_header(archi, "racine")}

  <!-- ═══ SLIDER HERO ═══ -->
  <section class="home-slider" aria-label="Galerie pergolas">
    {slides_html}
    <div class="home-slider-content">
      <h1>{SITE_NOM} — le guide de référence des pergolas en France</h1>
      <p>Prix, matériaux, installation, réglementation : tout pour choisir la pergola idéale.</p>
    </div>
  </section>

  <!-- ═══ INTRO : image à gauche + texte justifié à droite ═══ -->
  <section class="home-intro">
    <div class="home-intro-inner">
      {img_responsive("/images/home/slider-1.webp", "Pergola sur terrasse française", role="hero", loading="eager", fetchpriority="high", classe="home-intro-img")}
      <div class="home-intro-texte">
        <h2>Votre projet pergola commence ici</h2>
        <p>Bienvenue sur <strong>{SITE_NOM}</strong>, le site français dédié à l'univers des pergolas. Que vous prépariez l'installation d'une <strong>pergola bioclimatique</strong>, d'une <strong>pergola en bois</strong> ou en <strong>aluminium</strong>, vous trouverez ici toutes les informations pour faire le bon choix.</p>
        <p>Nos guides couvrent les prix du marché français 2025-2026, les démarches administratives (permis de construire, déclaration préalable), les techniques d'installation et tous les critères qui comptent vraiment pour réussir votre projet.</p>
        <p>Avec plus de <strong>60 pages détaillées</strong> et des articles ajoutés chaque semaine, nous accompagnons chaque année des milliers de propriétaires français dans leur projet d'aménagement extérieur.</p>
      </div>
    </div>
  </section>
  <!-- ═══ ADSENSE HAUT ═══ -->
  <div class="container">
    {bloc_adsense(ADSENSE_SLOT_HAUT, "horizontal")}
  </div>

  <!-- ═══ PILIERS ═══ -->
  <section class="home-section">
    <div class="container">
      <h2 class="section-titre">Nos guides thématiques</h2>
      <div class="piliers-grid">{cards}</div>
    </div>
  </section>

  <!-- ═══ ADSENSE MILIEU ═══ -->
  <div class="container">
    {bloc_adsense(ADSENSE_SLOT_MILIEU, "inArticle")}
  </div>

  <!-- ═══ DERNIERS ARTICLES ═══ -->
  <section class="home-section home-section-alt">
    <div class="container">
      <h2 class="section-titre">Nos derniers articles</h2>
      <div class="articles-grid">{derniers_cards}</div>
      <div style="text-align:center;margin-top:30px;">
        <a href="/blog.html" class="btn-hero">Voir tous nos articles →</a>
      </div>
    </div>
  </section>

  <!-- ═══ ADSENSE BAS ═══ -->
  <div class="container">
    {bloc_adsense(ADSENSE_SLOT_BAS, "horizontal")}
  </div>

  <!-- ═══ POURQUOI NOUS FAIRE CONFIANCE ═══ -->
  <section class="home-section">
    <div class="container">
      <h2 class="section-titre">Pourquoi nous faire confiance ?</h2>
      <div class="confiance-grid">
        <div class="confiance-item">
          <span class="icone">🎯</span>
          <h3>Infos à jour 2025-2026</h3>
          <p>Prix, normes et réglementation actualisés pour le marché français.</p>
        </div>
        <div class="confiance-item">
          <span class="icone">📚</span>
          <h3>60+ guides détaillés</h3>
          <p>Une couverture complète : matériaux, dimensions, installation, prix.</p>
        </div>
        <div class="confiance-item">
          <span class="icone">🇫🇷</span>
          <h3>100% français</h3>
          <p>Contenu adapté aux spécificités du marché et des démarches françaises.</p>
        </div>
      </div>
    </div>
  </section>

  {construire_footer("racine")}
  {lien_js()}
  {banner_cookies()}
</body></html>"""
    Path("index.html").write_text(html, encoding="utf-8")
    print("✅ index.html")

# ─── PAGE PILIER ──────────────────────────────────────────
# ─── PROMPTS IMAGES SPÉCIFIQUES PAR PILIER ────────────────
# Ces prompts décrivent VISUELLEMENT le sujet (pas l'id générique).
# Pour chaque pilier, on a 2 variantes : hero (large, architecturale) et détail.
# Si un pilier n'est pas mappé ici, on utilise un fallback générique propre.
PROMPTS_IMAGES_PILIERS = {
    "bioclimatique": {
        "hero":   "modern bioclimatic pergola with aluminum adjustable louvers rotating, contemporary Mediterranean terrace, outdoor dining area, clean architecture",
        "detail": "close-up of bioclimatic pergola aluminum louvers mechanism, adjustable slats detail, LED integrated lighting, modern design",
    },
    "bois": {
        "hero":   "elegant wooden pergola with exposed natural wood beams, warm tones, garden setting with outdoor furniture, wisteria climbing, provencal style",
        "detail": "close-up of wooden pergola beam joinery detail, natural wood grain texture, craftsmanship, outdoor lifestyle",
    },
    "aluminium": {
        "hero":   "modern aluminum pergola with clean white frame on contemporary terrace, flat slat roof, minimalist residential design, sleek lines",
        "detail": "aluminum pergola structure detail, precision engineered frame, matte powder-coated finish, architectural close-up",
    },
    "toiture": {
        "hero":   "pergola with transparent polycarbonate roof panels over outdoor living space, showing covered shelter function, sunny day with clear sky visible through roof",
        "detail": "detailed view of pergola roof options: polycarbonate panels, retractable canvas, glass roofing, materials comparison",
    },
    "dimensions": {
        "hero":   "spacious 4 meter by 3 meter aluminum pergola over outdoor dining table with six chairs, showing scale with furniture, wide angle garden shot",
        "detail": "pergola measurement context: dining set placement, human scale reference, outdoor kitchen area under structure",
    },
    "prix": {
        "hero":   "premium bioclimatic pergola on upscale residential terrace, high-end aluminum materials, integrated lighting, showcase quality and value",
        "detail": "luxury pergola installation showcasing premium finishes, automated louvers, glass sliding panels, modern affluent home",
    },
    "installation": {
        "hero":   "pergola installation in progress on concrete terrace, aluminum structure being mounted, professional construction view, technical scene",
        "detail": "close-up of pergola post anchor plate on concrete foundation, mounting hardware, professional installation detail, bolts and brackets",
    },
    "stores-occultation": {
        "hero":   "aluminum pergola with retractable canvas side curtains and shade fabric deployed, cozy ambiance, late afternoon warm light, outdoor living",
        "detail": "pergola side curtain detail, vertical roller blinds fabric texture, wind resistant shading system, outdoor privacy solution",
    },
    "terrasse-jardin": {
        "hero":   "beautiful wooden pergola integrated in lush french garden, climbing roses and wisteria vines, stone terrace, countryside charm",
        "detail": "pergola lifestyle scene, outdoor dining under vines, garden plants integration, french country ambiance",
    },
}

def prompt_image_pilier(pilier_id, variante="hero"):
    """Retourne un prompt visuel détaillé pour ce pilier.
    Si non mappé, fallback propre et générique (jamais juste l'id)."""
    mapping = PROMPTS_IMAGES_PILIERS.get(pilier_id)
    if mapping and variante in mapping:
        return mapping[variante]
    # Fallback générique propre (jamais juste "pergola id terrace garden")
    if variante == "hero":
        return "modern pergola over contemporary terrace, professional outdoor living architecture, natural daylight"
    return "pergola structural detail, architectural close-up, high-quality outdoor design"

# ─── PROMPT IMAGE SECONDAIRE (enrichissement contextuel) ────
def prompt_image_secondaire(secondaire, pilier):
    """Construit un prompt visuel enrichi pour une page secondaire.
    Utilise le mot-clé + le contexte du pilier parent pour produire
    une image spécifique au sujet."""
    mot_cle   = secondaire.get("mot_cle", secondaire.get("titre", "")).lower()
    pilier_id = pilier.get("id", "")

    # Mots indicateurs que FLUX comprend bien
    contexte_mots = {
        "bioclimatique": "with adjustable aluminum louvers, contemporary design, automated roof",
        "bois":          "wooden structure, natural wood tones, garden ambiance",
        "aluminium":     "aluminum frame, modern minimalist design, sleek matte finish",
        "toiture":       "with visible roof covering, material focus, shelter function",
        "dimensions":    "showing scale with outdoor furniture for reference, wide angle",
        "prix":          "premium quality showcase, high-end residential setting",
        "installation":  "installation detail, construction context, technical view",
        "stores-occultation": "with shade fabric and curtains, cozy enclosed ambiance",
        "terrasse-jardin":    "integrated in lush garden, french country style",
    }
    contexte = contexte_mots.get(pilier_id, "outdoor terrace setting")

    # Nettoyer les pluriels/accents pour FLUX
    sujet_en = mot_cle.replace("é", "e").replace("è", "e").replace("ê", "e")
    return f"{sujet_en} pergola, {contexte}, professional architectural photography"

# ─── PROMPT IMAGE BLOG (article) ──────────────────────────
def prompt_image_blog(sujet):
    """Prompt visuel pour un article de blog."""
    mot_cle = sujet.get("mot_cle", "").lower()
    titre   = sujet.get("titre", "").lower()
    # Priorité au mot-clé s'il est précis
    base = mot_cle if len(mot_cle) > 5 else titre
    base_en = base.replace("é", "e").replace("è", "e").replace("ê", "e")
    return f"pergola lifestyle scene, {base_en}, outdoor living inspiration, warm natural light, editorial photography"

def generer_page_pilier(pilier, archi, keywords=None, articles=None):
    print(f"📌 Pilier : {pilier['titre']}...")
    articles = articles or []

    # 1 image FLUX.1.1-pro : hero en haut (la 2ème image du milieu a été supprimée
    # car elle n'apportait aucune information utile au lecteur et nuisait au flux de lecture)
    img1 = get_image(prompt_image_pilier(pilier['id'], "hero"),
                     modele="dev",
                     chemin_local=f"images/piliers/{pilier['slug']}-1.webp")

    kw_block = formater_keywords_prompt(pilier['id'], keywords or {})

    # Prompt renforcé : HTML PUR, exemples explicites, interdiction du Markdown
    prompt = f"""Tu es expert SEO et rédacteur web pergolas France, avec 10 ans d'expérience.
Tu rédiges une page pilier PARFAITEMENT optimisée SEO : {pilier['titre']}
{kw_block}
OBJECTIF : cette page doit être LA référence française sur le sujet, ranker top 3 Google.

⚠️ CONSIGNE CRITIQUE DE FORMAT — LIRE ABSOLUMENT AVANT DE COMMENCER ⚠️
Tu produis UNIQUEMENT du HTML pur. INTERDICTION ABSOLUE d'utiliser :
- du Markdown (**gras**, *italique*, ## titre, ### sous-titre, - liste)
- des caractères dièse (#) en début de ligne
- des astérisques doubles (**) autour des mots
- des tirets en début de ligne pour les listes

Tu utilises EXCLUSIVEMENT les balises HTML suivantes dans <CONTENU> :
<h2>, <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, <a>, <table>, <thead>, <tbody>, <tr>, <th>, <td>

EXEMPLE de ce que tu DOIS produire dans <CONTENU> :
<h2>Pourquoi choisir une pergola bioclimatique ?</h2>
<p>La <strong>pergola bioclimatique</strong> offre un confort thermique inégalé...</p>
<h3>Les atouts majeurs</h3>
<ul>
  <li>Régulation automatique de la lumière</li>
  <li>Protection contre la pluie</li>
</ul>

EXEMPLE de ce que tu NE DOIS PAS produire :
## Pourquoi choisir...        ← INTERDIT (markdown)
**pergola bioclimatique**     ← INTERDIT (markdown)
- Régulation automatique      ← INTERDIT (markdown)

CONSIGNES DE FOND :
1. Français naturel expert, public acheteur français, ton professionnel mais accessible
2. Couverture EXHAUSTIVE du sujet — le lecteur ne doit avoir aucune question sans réponse
3. Prix réalistes en euros (marché France 2025-2026), avec fourchettes précises (ex: "entre 3 500 € et 6 800 € pour du 3x4m posé")
4. Longueur : 3000 à 4000 mots dans <CONTENU> — NON NÉGOCIABLE
5. Exemples concrets, cas pratiques, chiffres précis
6. Mention de marques/fabricants français connus quand pertinent
7. Au moins 1 lien externe sortant vers une source officielle (service-public.fr, ADEME, AFNOR...)

STRUCTURE HN DANS <CONTENU> :
- PAS de H1 (il est déjà géré ailleurs)
- 6 à 10 <h2> couvrant : définition/principe, prix détaillé, matériaux, installation, réglementation, choix/critères, comparatif, entretien
- 2 à 3 <h3> sous chaque <h2> pour approfondir
- Au moins 3 <ul> (critères, avantages, étapes...)
- 1 <table> comparatif minimum avec <thead> et <tbody>
- Chaque <h2> intègre un mot-clé longue traîne naturellement

DENSITÉ MOT-CLÉ :
- Mot-clé principal : 1 à 1,5% du texte (naturellement, pas de bourrage)
- Variantes sémantiques (LSI) partout
- Mot-clé principal dans : H1, première phrase de l'intro, au moins 3 <h2>, 5+ fois dans le corps

Produis ta réponse STRICTEMENT dans ce format, avec les balises exactement comme ceci :

<META>description 150-155 car. avec mot-clé principal dans les 60 premiers caractères</META>
<H1>H1 optimisé avec mot-clé principal + année 2026 si pertinent</H1>
<INTRO>100-150 mots en HTML (balises <p>, <strong>, etc.), mot-clé principal dans la 1ère phrase</INTRO>
<CONTENU>
<h2>...</h2>
<p>...</p>
[... 3000-4000 mots de HTML pur ...]
</CONTENU>
<FAQ1Q>question longue traîne complète</FAQ1Q>
<FAQ1R>réponse 3-4 phrases précises avec chiffres</FAQ1R>
<FAQ2Q>...</FAQ2Q><FAQ2R>...</FAQ2R>
<FAQ3Q>...</FAQ3Q><FAQ3R>...</FAQ3R>
<FAQ4Q>...</FAQ4Q><FAQ4R>...</FAQ4R>
<FAQ5Q>...</FAQ5Q><FAQ5R>...</FAQ5R>
<FAQ6Q>...</FAQ6Q><FAQ6R>...</FAQ6R>
<FAQ7Q>...</FAQ7Q><FAQ7R>...</FAQ7R>"""

    # Génération avec validation + retry si contenu trop court ou vide
    texte = appeler_claude(prompt, max_tokens=16000)
    contenu_brut = extraire_balise(texte, "CONTENU") or ""
    nb_mots = compter_mots_html(contenu_brut)

    if nb_mots < 1500:
        print(f"  ⚠️ Contenu pilier trop court ({nb_mots} mots), nouvel essai...")
        texte = appeler_claude(prompt, max_tokens=16000)
        contenu_brut = extraire_balise(texte, "CONTENU") or ""
        nb_mots = compter_mots_html(contenu_brut)
        print(f"  ↪ Après retry : {nb_mots} mots")

    # Nettoyage Markdown résiduel → HTML propre
    contenu = nettoyer_markdown_vers_html(contenu_brut)

    h1    = extraire_balise(texte, "H1") or pilier["titre"]
    meta  = extraire_balise(texte, "META") or pilier["description"]
    intro = nettoyer_markdown_vers_html(extraire_balise(texte, "INTRO") or "")

    # Sécurité : si l'intro ne contient pas de <p>, on l'enveloppe
    if intro and "<p" not in intro:
        intro = f"<p>{intro}</p>"

    # FAQ (7 questions)
    qrs = []
    faq_html = ""
    for i in range(1, 8):
        q = extraire_balise(texte, f"FAQ{i}Q")
        r = extraire_balise(texte, f"FAQ{i}R")
        if q and r:
            r_clean = nettoyer_markdown_vers_html(r)
            qrs.append({"q": q, "r": r})
            faq_html += f'<div class="faq-item"><button class="faq-question">{q}</button><div class="faq-reponse">{r_clean}</div></div>\n'

    # ─── Cards visuelles des pages secondaires ─────────────────
    # Remplace l'ancienne liste textuelle par une grille de cards
    # (miniature + titre cliquable + extrait + CTA)
    # IMPORTANT : ce bloc est affiché EN HAUT de la page (juste après l'intro) pour :
    #  - meilleur UX (secondaires visibles sans scroll énorme)
    #  - meilleur SEO (liens internes plus proches du début du HTML)
    cards_sec_html = ""
    if pilier["secondaires"]:
        # Titre dynamique basé sur le pilier (contient le mot-clé, bon pour SEO)
        titre_pilier_bas = pilier['titre'].lower()
        titre_section = f"Tout savoir sur {titre_pilier_bas}"
        intro_section = f"Explorez les différents aspects de {titre_pilier_bas} à travers nos guides thématiques."
        cards_sec_html = (
            f'<section class="pilier-secondaires">'
            f'<h2>{titre_section}</h2>'
            f'<p class="pilier-secondaires-intro">{intro_section}</p>'
            f'<div class="sec-grid">'
        )
        for s in pilier["secondaires"]:
            # L'image secondaire a le chemin : images/secondaires/{pilier_id}-{slug}.webp
            img_path = f"/images/secondaires/{pilier['id']}-{s['slug']}.webp"
            # Extrait réel basé sur la meta description générée (pas le titre dupliqué)
            excerpt = excerpt_card_secondaire(pilier['id'], s)
            img_sec_card = img_responsive(img_path, s['titre'], role="card",
                                          loading="lazy", classe="sec-card-img")
            cards_sec_html += f'''
          <a href="/{pilier["id"]}/{s["slug"]}.html" class="sec-card">
            {img_sec_card}
            <div class="sec-card-body">
              <span class="sec-card-titre">{s['titre']}</span>
              <p class="sec-card-excerpt">{excerpt}</p>
              <span class="sec-card-cta">Lire la suite →</span>
            </div>
          </a>'''
        cards_sec_html += '</div></section>'

    # Articles récents du pilier (maillage statique)
    arts_pilier = [a for a in articles if a.get("pilier_id") == pilier["id"]][:4]
    arts_html = ""
    if arts_pilier:
        arts_html = '<section class="articles-pilier"><h2>Nos derniers articles</h2><div class="articles-grid">'
        for art in arts_pilier:
            thumb = art.get("thumb", "")
            img_html = img_responsive(thumb, art["titre"], role="card", loading="lazy", classe="card-image") if thumb else ''
            arts_html += f"""
            <a href="/blog/{art['slug']}.html" class="article-card">
                {img_html}
                <div class="card-body">
                    <h3>{art['titre']}</h3>
                    <p>{art.get('description','')[:80]}...</p>
                </div>
            </a>"""
        arts_html += '</div></section>'

    date_modified = datetime.now().strftime("%Y-%m-%d")

    # Schemas
    breadcrumb_schema = schema_breadcrumb([
        {"name": "Accueil", "url": f"{SITE_URL}/"},
        {"name": pilier["titre"], "url": f"{SITE_URL}/{pilier['slug']}.html"}
    ])
    faq_schema     = schema_faq(qrs)
    article_schema = schema_article(h1, meta, img1["url"], date_published=date_modified, date_modified=date_modified)

    howto_script = ""
    if pilier["id"] == "installation":
        etapes = [
            {"nom": "Préparer le terrain", "texte": "Délimitez la zone d'installation et vérifiez la planéité du sol."},
            {"nom": "Réaliser les fondations", "texte": "Coulez des semelles béton ou installez des platines selon le type de sol."},
            {"nom": "Monter la structure", "texte": "Assemblez les poteaux et la charpente selon les instructions du fabricant."},
            {"nom": "Poser la toiture", "texte": "Installez les lames, panneaux ou toiture selon le modèle choisi."},
            {"nom": "Finitions", "texte": "Vérifiez l'aplomb, serrez les fixations et effectuez les réglages finaux."},
        ]
        howto_script = f'<script type="application/ld+json">{schema_howto(h1, etapes)}</script>'

    # ─── CSS spécifique aux pages piliers (inline) ───────────
    css_pilier = '''
  <style>
    /* Hero pilier : image bandeau fine, titre en dessous (pas superposé) */
    .pilier-hero-v2{margin:0 0 30px;}
    .pilier-hero-v2 img{width:100%;height:280px;object-fit:cover;border-radius:10px;display:block;}
    .pilier-hero-title{max-width:900px;margin:24px auto 0;padding:0 20px;}
    .pilier-hero-title h1{font-family:Georgia,serif;color:var(--vert,#2d5a3d);font-size:2.2rem;margin:0 0 14px;line-height:1.2;}
    .pilier-hero-title .intro{color:#333;font-size:1.08rem;line-height:1.7;}
    .pilier-hero-title .intro p{margin:0 0 10px;}

    /* Contenu principal : typographie lisible */
    .article-body{max-width:820px;margin:0 auto;line-height:1.75;color:#222;font-size:1.02rem;}
    .article-body h2{font-family:Georgia,serif;color:var(--vert,#2d5a3d);font-size:1.6rem;margin:36px 0 16px;padding-bottom:10px;border-bottom:2px solid #e8e8e0;}
    .article-body h3{color:#2d5a3d;font-size:1.2rem;margin:26px 0 12px;}
    .article-body p{margin:0 0 16px;}
    .article-body ul,.article-body ol{margin:0 0 18px;padding-left:24px;}
    .article-body li{margin:0 0 8px;}
    .article-body table{width:100%;border-collapse:collapse;margin:20px 0;font-size:.95rem;}
    .article-body th{background:#2d5a3d;color:#fff;padding:10px;text-align:left;}
    .article-body td{padding:10px;border-bottom:1px solid #e0e0e0;}
    .article-body tr:nth-child(even) td{background:#fafaf7;}
    .article-body strong{color:#2d5a3d;}
    .article-body a{color:#2d5a3d;text-decoration:underline;}
    .article-img-milieu{width:100%;max-width:820px;margin:30px auto;display:block;border-radius:8px;}

    /* Grille cards secondaires (affichée en haut, juste après l'intro) */
    /* Hérite de la largeur de .container — pas de max-width propre */
    .pilier-secondaires{margin:40px 0 50px;padding:30px 0 0;
      border-top:1px solid #e8e8e0;}
    .pilier-secondaires h2{font-family:Georgia,serif;color:var(--vert,#2d5a3d);
      font-size:1.8rem;text-align:center;margin:0 0 10px;position:relative;}
    .pilier-secondaires h2::after{content:"";display:block;width:80px;height:2px;
      background:#c5a572;margin:14px auto 0;}
    .pilier-secondaires-intro{text-align:center;color:#666;font-size:1.02rem;
      margin:0 auto 30px;max-width:680px;line-height:1.6;}
    .sec-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:22px;}
    .sec-card{background:#fff;border-radius:10px;overflow:hidden;text-decoration:none;color:inherit;
      transition:transform .2s,box-shadow .2s;border:1px solid #e8e8e0;display:flex;flex-direction:column;}
    .sec-card:hover{transform:translateY(-3px);box-shadow:0 10px 30px rgba(45,90,61,.15);}
    .sec-card-img{width:100%;height:160px;object-fit:cover;display:block;background:#f0ede5;}
    .sec-card-body{padding:16px;flex:1;display:flex;flex-direction:column;}
    .sec-card-titre{font-weight:600;color:#2d5a3d;font-size:1.05rem;margin-bottom:8px;display:block;}
    .sec-card-excerpt{color:#555;font-size:.9rem;line-height:1.5;margin:0 0 12px;flex:1;}
    .sec-card-cta{color:#2d5a3d;font-size:.88rem;font-weight:600;}
  </style>'''

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{h1} | {SITE_NOM}</title>
  <meta name="description" content="{meta}">
  {meta_commune()}
  {meta_sociales(
    titre=h1,
    description=meta,
    image_url=img1["url"],
    url_page=f"{SITE_URL}/{pilier['slug']}.html",
    type_og="article"
  )}
  <link rel="canonical" href="{SITE_URL}/{pilier['slug']}.html">
  <!-- Preload de l'image LCP responsive : le navigateur télécharge la bonne taille selon l'écran -->
  {_preload_responsive(img1['url'], role="hero")}
  {lien_css()}
{css_pilier}
  <script type="application/ld+json">{article_schema}</script>
  <script type="application/ld+json">{breadcrumb_schema}</script>
  {f'<script type="application/ld+json">{faq_schema}</script>' if faq_schema else ''}
  {howto_script}
</head>
<body>
  {construire_header(archi, "pilier", pilier['id'])}
  <main class="container page-pilier">
    <nav class="fil-ariane">
      <a href="/">Accueil</a> › <span>{pilier['titre']}</span>
    </nav>

    <!-- Hero : image fine + titre en dessous (pas de superposition) -->
    <div class="pilier-hero-v2">
      {img_responsive(img1['url'], h1, role="hero", loading="eager", fetchpriority="high", width=1200, height=630)}
    </div>
    <div class="pilier-hero-title">
      <h1>{h1}</h1>
      {bloc_date_auteur_top(date_modified, date_modified)}
      <div class="intro">{intro}</div>
    </div>

    {cards_sec_html}

    <div class="page-layout">
      <article class="contenu-principal">
        {bloc_adsense(ADSENSE_SLOT_HAUT, "horizontal")}
        <div class="article-body">{contenu}</div>

        <div class="faq-section">
          <h2>Questions fréquentes sur {pilier['titre'].lower()}</h2>
          {faq_html}
        </div>

        {bloc_auteur_fin_article()}

        {arts_html}
      </article>
      <aside class="sidebar">
        <div class="widget">
          <h3>Dans ce guide</h3>
          {''.join(f'<a href="/{pilier["id"]}/{s["slug"]}.html" class="lien-secondaire">→ {s["titre"]}</a>' for s in pilier["secondaires"])}
        </div>
        {bloc_adsense(ADSENSE_SLOT_SIDEBAR, "sidebar")}
      </aside>
    </div>
  </main>
  {construire_footer("pilier")}
  <script>const PILIER_ID = "{pilier['id']}";</script>
  {lien_js()}
  {banner_cookies()}
</body></html>"""

    Path(f"{pilier['slug']}.html").write_text(html, encoding="utf-8")
    print(f"  ✅ {pilier['slug']}.html ({nb_mots} mots)")

# ─── PAGE SECONDAIRE ──────────────────────────────────────
def generer_page_secondaire(secondaire, pilier, archi, keywords=None, articles=None):
    print(f"  📄 Secondaire : {secondaire['titre']}...")
    articles = articles or []

    img = get_image(prompt_image_secondaire(secondaire, pilier),
                    modele="schnell",
                    chemin_local=f"images/secondaires/{pilier['id']}-{secondaire['slug']}.webp")

    # KW liés
    kw_block = ""
    if keywords and pilier['id'] in keywords:
        data    = keywords[pilier['id']]
        termes  = secondaire.get('mot_cle', '').lower().split()
        kw_lies = [
            kw for kw in data.get('secondaires', []) + data.get('longue_traine', [])
            if any(t in kw['kw'].lower() for t in termes if len(t) > 3)
        ][:12]
        if kw_lies:
            kw_block = f"\n=== MOTS-CLÉS SEO (Ahrefs France) ===\nMot-clé cible : {secondaire['mot_cle']}\n"
            for kw in kw_lies:
                kw_block += f"  - {kw['kw']} ({kw['vol']:,}/mois)\n"
            kw_block += "======================================\n"

    prompt = f"""Tu es expert SEO et rédacteur web pergolas France, spécialisé dans les pages de conversion.
Tu rédiges une page secondaire optimisée SEO : {secondaire['titre']}
Guide parent : {pilier['titre']}
{kw_block}
OBJECTIF : ranker sur une requête ciblée à forte intention d'achat, convaincre le lecteur.

⚠️ CONSIGNE CRITIQUE DE FORMAT ⚠️
Tu produis UNIQUEMENT du HTML pur dans <CONTENU>. INTERDIT d'utiliser :
- Markdown (**gras**, *italique*, ## titre, - liste)
- Dièses (#) ou astérisques en début de ligne

Utilise EXCLUSIVEMENT : <h2>, <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, <a>, <table>, <thead>, <tbody>, <tr>, <th>, <td>

EXEMPLE CORRECT :
<h2>Quel prix pour ce modèle ?</h2>
<p>Le <strong>prix moyen</strong> se situe entre 2500 € et 4500 €...</p>
<ul><li>Matériau aluminium : 2500 €</li></ul>

EXEMPLE INTERDIT :
## Quel prix...
**prix moyen**
- Matériau aluminium

CONSIGNES DE FOND :
1. Français naturel expert, orienté aide à la décision achat
2. Prix réalistes en euros (marché France 2025-2026), fourchettes précises
3. Longueur : 1400 à 1800 mots dans <CONTENU> — ne pas descendre sous 1400
4. Ton expert rassurant, lève les objections
5. Exemples concrets, cas d'usage typiques, mini-comparatifs
6. Au moins 2 <ul> dans le corps

STRUCTURE HN DANS <CONTENU> :
- PAS de H1 (géré ailleurs)
- 5 à 7 <h2> : prix, pour qui/quelle surface, modèles/options, installation, réglementation si pertinent, critères de choix, erreurs à éviter
- <h3> sous les <h2> qui s'y prêtent (surtout "prix" et "modèles")
- Minimum 2 <ul>
- Idéalement 1 <table> si pertinent

DENSITÉ MOT-CLÉ :
- Mot-clé principal dans H1, 1ère phrase intro, au moins 2 <h2>, 4+ fois dans le corps
- Variantes longue traîne réparties naturellement

Format STRICT :
<META>description 150-155 car. avec mot-clé principal</META>
<H1>H1 optimisé avec mot-clé exact</H1>
<INTRO>80-120 mots en HTML (<p>, <strong>), mot-clé dans la 1ère phrase</INTRO>
<CONTENU>
<h2>...</h2>
<p>...</p>
[... 1400-1800 mots de HTML pur ...]
</CONTENU>
<FAQ1Q>...</FAQ1Q><FAQ1R>...</FAQ1R>
<FAQ2Q>...</FAQ2Q><FAQ2R>...</FAQ2R>
<FAQ3Q>...</FAQ3Q><FAQ3R>...</FAQ3R>
<FAQ4Q>...</FAQ4Q><FAQ4R>...</FAQ4R>"""

    texte = appeler_claude(prompt, max_tokens=8000)
    contenu_brut = extraire_balise(texte, "CONTENU") or ""
    nb_mots = compter_mots_html(contenu_brut)

    if nb_mots < 800:
        print(f"  ⚠️ Contenu secondaire trop court ({nb_mots} mots), nouvel essai...")
        texte = appeler_claude(prompt, max_tokens=8000)
        contenu_brut = extraire_balise(texte, "CONTENU") or ""
        nb_mots = compter_mots_html(contenu_brut)

    contenu = nettoyer_markdown_vers_html(contenu_brut)
    h1      = extraire_balise(texte, "H1") or secondaire["titre"]
    meta    = extraire_balise(texte, "META") or secondaire["titre"]
    intro   = nettoyer_markdown_vers_html(extraire_balise(texte, "INTRO") or "")
    if intro and "<p" not in intro:
        intro = f"<p>{intro}</p>"

    qrs      = []
    faq_html = ""
    for i in range(1, 5):
        q = extraire_balise(texte, f"FAQ{i}Q")
        r = extraire_balise(texte, f"FAQ{i}R")
        if q and r:
            r_clean = nettoyer_markdown_vers_html(r)
            qrs.append({"q": q, "r": r})
            faq_html += f'<div class="faq-item"><button class="faq-question">{q}</button><div class="faq-reponse">{r_clean}</div></div>\n'

    # Liens sœurs dans la sidebar (textuels)
    liens_soeurs = "".join(
        f'<a href="/{pilier["id"]}/{s["slug"]}.html">→ {s["titre"]}</a>\n'
        for s in pilier["secondaires"] if s["slug"] != secondaire["slug"]
    )

    # Articles de blog liés
    arts_connexes = generer_liens_blog_sur_secondaire(
        pilier['id'], secondaire['slug'], articles
    )

    # ─── NOUVEAU : Maillage interne visuel vers autres secondaires ─
    # Cards : titre (lien) + visuel en dessous (pas de balise Hn)
    maillage_html = ""
    autres_sec = [s for s in pilier["secondaires"] if s["slug"] != secondaire["slug"]]
    if autres_sec:
        # Max 6 autres pages secondaires pour rester lisible
        maillage_html = '<section class="maillage-secondaires"><h2>À découvrir aussi dans ce guide</h2><div class="maillage-grid">'
        for s in autres_sec[:6]:
            img_path = f"/images/secondaires/{pilier['id']}-{s['slug']}.webp"
            img_maillage = img_responsive(img_path, s['titre'], role="thumb",
                                          loading="lazy", classe="maillage-img")
            maillage_html += f'''
            <div class="maillage-card">
              <a href="/{pilier["id"]}/{s["slug"]}.html" class="maillage-titre">{s["titre"]}</a>
              <a href="/{pilier["id"]}/{s["slug"]}.html" class="maillage-img-link">
                {img_maillage}
              </a>
            </div>'''
        maillage_html += '</div></section>'

    date_modified = datetime.now().strftime("%Y-%m-%d")

    breadcrumb_schema = schema_breadcrumb([
        {"name": "Accueil", "url": f"{SITE_URL}/"},
        {"name": pilier["titre"], "url": f"{SITE_URL}/{pilier['slug']}.html"},
        {"name": secondaire["titre"], "url": f"{SITE_URL}/{pilier['id']}/{secondaire['slug']}.html"}
    ])
    faq_schema     = schema_faq(qrs)
    article_schema = schema_article(h1, meta, img["url"], date_published=date_modified, date_modified=date_modified)

    # CSS spécifique secondaires (maillage + cohérence avec pilier)
    css_sec = '''
  <style>
    .article-body{max-width:820px;margin:0 auto;line-height:1.75;color:#222;font-size:1.02rem;}
    .article-body h2{font-family:Georgia,serif;color:var(--vert,#2d5a3d);font-size:1.45rem;margin:30px 0 14px;padding-bottom:8px;border-bottom:2px solid #e8e8e0;}
    .article-body h3{color:#2d5a3d;font-size:1.15rem;margin:22px 0 10px;}
    .article-body p{margin:0 0 14px;}
    .article-body ul,.article-body ol{margin:0 0 16px;padding-left:22px;}
    .article-body li{margin:0 0 6px;}
    .article-body table{width:100%;border-collapse:collapse;margin:16px 0;font-size:.95rem;}
    .article-body th{background:#2d5a3d;color:#fff;padding:10px;text-align:left;}
    .article-body td{padding:10px;border-bottom:1px solid #e0e0e0;}
    .article-body strong{color:#2d5a3d;}
    .article-body a{color:#2d5a3d;text-decoration:underline;}

    /* Maillage interne visuel vers autres secondaires */
    /* Hérite de la largeur de .container — pas de max-width/margin propres */
    .maillage-secondaires{margin:50px 0;}
    .maillage-secondaires h2{font-family:Georgia,serif;color:var(--vert,#2d5a3d);font-size:1.6rem;text-align:center;margin:0 0 26px;}
    .maillage-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:20px;}
    .maillage-card{display:flex;flex-direction:column;background:#fff;border:1px solid #e8e8e0;border-radius:8px;overflow:hidden;transition:transform .2s,box-shadow .2s;}
    .maillage-card:hover{transform:translateY(-2px);box-shadow:0 8px 24px rgba(45,90,61,.12);}
    .maillage-titre{padding:14px 14px 10px;font-weight:600;color:#2d5a3d;text-decoration:none;font-size:1rem;line-height:1.35;display:flex;align-items:flex-start;min-height:62px;box-sizing:border-box;}
    .maillage-titre:hover{text-decoration:underline;}
    .maillage-img-link{display:block;margin-top:auto;}
    .maillage-img{width:100%;height:140px;object-fit:cover;display:block;background:#f0ede5;}
  </style>'''

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{h1} | {SITE_NOM}</title>
  <meta name="description" content="{meta}">
  {meta_commune()}
  {meta_sociales(
    titre=h1,
    description=meta,
    image_url=img["url"],
    url_page=f"{SITE_URL}/{pilier['id']}/{secondaire['slug']}.html",
    type_og="article"
  )}
  <link rel="canonical" href="{SITE_URL}/{pilier['id']}/{secondaire['slug']}.html">
  <!-- Preload de l'image LCP responsive : le navigateur télécharge la bonne taille selon l'écran -->
  {_preload_responsive(img['url'], role="hero")}
  {lien_css()}
{css_sec}
  <script type="application/ld+json">{article_schema}</script>
  <script type="application/ld+json">{breadcrumb_schema}</script>
  {f'<script type="application/ld+json">{faq_schema}</script>' if faq_schema else ''}
</head>
<body>
  {construire_header(archi, "secondaire", pilier['id'])}
  <main class="container">
    <nav class="fil-ariane">
      <a href="/">Accueil</a> ›
      <a href="/{pilier['slug']}.html">{pilier['titre']}</a> ›
      <span>{secondaire['titre']}</span>
    </nav>
    <div class="page-layout">
      <article class="contenu-principal">
        {img_responsive(img['url'], h1, role="hero", loading="eager", fetchpriority="high", width=1200, height=630, classe="article-img")}
        <h1>{h1}</h1>
        {bloc_date_auteur_top(date_modified, date_modified)}
        <div class="intro">{intro}</div>
        <div class="article-body">{contenu}</div>
        {bloc_adsense(ADSENSE_SLOT_MILIEU, "inArticle")}
        <div class="faq-section">
          <h2>Questions fréquentes</h2>{faq_html}
        </div>
        <div class="articles-connexes">
          <h2>Articles de blog sur ce sujet</h2>
          {arts_connexes}
        </div>
        {bloc_auteur_fin_article()}
      </article>
      <aside class="sidebar">
        <div class="widget">
          <h3>Guide {pilier['titre']}</h3>
          <a href="/{pilier['slug']}.html">← Retour au guide complet</a>
          <h4 style="margin:12px 0 8px;font-size:.9rem;color:var(--vert)">Pages du guide</h4>
          {liens_soeurs}
        </div>
        {bloc_adsense(ADSENSE_SLOT_SIDEBAR, "sidebar")}
      </aside>
    </div>

    {maillage_html}
  </main>
  {construire_footer("secondaire")}
  <script>const PILIER_ID="{pilier['id']}"; const PAGE_SLUG="{secondaire['slug']}";</script>
  {lien_js()}
  {banner_cookies()}
</body></html>"""

    Path(f"{pilier['id']}/{secondaire['slug']}.html").write_text(html, encoding="utf-8")
    print(f"    ✅ {pilier['id']}/{secondaire['slug']}.html ({nb_mots} mots)")

    # Sauvegarde de la meta description pour enrichir les cards pilier
    # (évite d'afficher le titre dupliqué dans les extraits)
    sauvegarder_meta_secondaire(pilier['id'], secondaire['slug'], meta)

# ─── CACHE DES EXCERPTS SECONDAIRES ───────────────────────
# On stocke la meta description de chaque page secondaire générée.
# Ces excerpts servent ensuite à enrichir les cards affichées sur les piliers
# (évite la duplication titre=description sur les cards).

def charger_meta_secondaires():
    """Charge le cache des metas secondaires (pour les cards piliers)."""
    f = Path("secondaires_meta.json")
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def sauvegarder_meta_secondaire(pilier_id, slug, meta):
    """Ajoute/met à jour la meta description d'une page secondaire.
    Format clé : '{pilier_id}/{slug}'."""
    cache = charger_meta_secondaires()
    cache[f"{pilier_id}/{slug}"] = meta
    Path("secondaires_meta.json").write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def excerpt_card_secondaire(pilier_id, secondaire):
    """Renvoie le texte à afficher sous le titre sur les cards du pilier.
    Priorité :
    1. Meta description de la page (générée par Claude, 150-155 car.)
    2. Description statique de architecture.json (si différente du titre)
    3. Fallback générique basé sur le titre
    """
    # Tentative 1 : meta cachée
    cache = charger_meta_secondaires()
    meta = cache.get(f"{pilier_id}/{secondaire['slug']}", "")
    if meta and meta.strip() and meta.strip().lower() != secondaire['titre'].strip().lower():
        # Tronquer proprement à ~120 caractères sur une frontière de mot
        if len(meta) > 130:
            return meta[:127].rsplit(" ", 1)[0] + "…"
        return meta
    # Tentative 2 : description d'architecture.json (si elle est "utile")
    desc = secondaire.get("description", "").strip()
    titre = secondaire.get("titre", "").strip()
    if desc and desc.lower() != titre.lower() and len(desc) > len(titre) + 10:
        if len(desc) > 130:
            return desc[:127].rsplit(" ", 1)[0] + "…"
        return desc
    # Tentative 3 : fallback générique contextualisé
    return f"Découvrez notre guide sur {titre.lower()} : conseils, prix et bonnes pratiques pour votre projet en 2026."

# ─── PROMPTS SPÉCIALISÉS PAR FORMAT ─────────────────────
# Chaque format a son propre prompt Claude avec structure différente.
# Toutes les règles communes (titre double-objectif, HTML pur) sont partagées.

def _regles_communes_blog(sujet):
    """Règles communes à TOUS les formats (titre, HTML pur, copyright, etc.)
    Renvoie un bloc texte à inclure dans chaque prompt."""
    return f"""═══════════════════════════════════════════════════════
⚠️ RÈGLE N°1 : TITRE DOUBLE-OBJECTIF (SEO + DISCOVER)
═══════════════════════════════════════════════════════
Ton titre <H1_OPTIMISE> DOIT satisfaire SIMULTANÉMENT 3 critères :

1️⃣ SEO : contenir le mot-clé principal "{sujet['mot_cle']}" OU une variante très proche
2️⃣ DISCOVER : formulé de manière ENGAGEANTE (question, chiffre, bénéfice, urgence, comparaison)
3️⃣ HONNÊTETÉ : la promesse du titre doit être tenue dans l'article

RÈGLES TECHNIQUES du <H1_OPTIMISE> :
- Longueur : 50 à 70 caractères (idéal mobile Discover)
- Mot-clé positionné DANS les 45 premiers caractères si possible
- Langage naturel, PAS de bourrage SEO
- Style journalistique français

❌ À ÉVITER : clickbait vulgaire, sensationnalisme, majuscules intempestives, promesses non tenues

═══════════════════════════════════════════════════════
⚠️ RÈGLE N°2 : HTML PUR DANS <CONTENU>
═══════════════════════════════════════════════════════
INTERDICTION absolue de Markdown (**gras**, *italique*, ## titre, - liste, dièses).
Utilise EXCLUSIVEMENT : <h2>, <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, <a>

EXEMPLE CORRECT : <h2>Titre</h2><p>Texte avec <strong>mot-clé</strong>.</p><ul><li>Item</li></ul>
EXEMPLE INTERDIT : ## Titre, **mot-clé**, - item

DENSITÉ MOT-CLÉ :
- Mot-clé cible "{sujet['mot_cle']}" dans 1ère phrase intro, au moins 1 <h2>, 3+ fois dans le corps
- Variantes sémantiques naturellement"""


def prompt_blog_guide(sujet, kw_block, maillage_instructions):
    """FORMAT 1 : Guide classique (format universel, ~35% des articles).
    Structure : intro → 4-6 H2 thématiques → FAQ en bas."""
    return f"""Tu es expert SEO et rédacteur web pergolas France.
Tu rédiges un GUIDE COMPLET DOUBLE-OBJECTIF (SEO + Discover) sur : {sujet['titre']}
Mot-clé cible : {sujet['mot_cle']}
{kw_block}
{maillage_instructions}

OBJECTIF : guide utile, concret, pédagogique, qui répond à toutes les questions du lecteur.

{_regles_communes_blog(sujet)}

═══════════════════════════════════════════════════════
STRUCTURE SPÉCIFIQUE "GUIDE CLASSIQUE" :
═══════════════════════════════════════════════════════
- Longueur : 1200 à 1600 mots dans <CONTENU>
- 4 à 6 <h2> thématiques : contexte/problème, solutions/points clés, cas pratique, erreurs à éviter, conseil final
- Des <h3> là où ça approfondit (pas systématique)
- Au moins 2 <ul> pour aérer
- Prix en euros (marché France 2026), conseils actionnables
- Au moins 1 exemple concret avec chiffres
- Liens de maillage dans le corps du texte (dans des <p>)

Format STRICT de ta réponse :
<H1_OPTIMISE>titre 50-70 car. avec mot-clé + angle engageant</H1_OPTIMISE>
<META>description 150-155 car. avec mot-clé</META>
<INTRO>80-120 mots en HTML (<p>, <strong>) : crochet + promesse + mot-clé</INTRO>
<CONTENU>
<h2>...</h2><p>...</p>
[... 1200-1600 mots HTML pur, 4-6 h2 thématiques ...]
</CONTENU>
<FAQ1Q>...</FAQ1Q><FAQ1R>...</FAQ1R>
<FAQ2Q>...</FAQ2Q><FAQ2R>...</FAQ2R>
<FAQ3Q>...</FAQ3Q><FAQ3R>...</FAQ3R>
<FAQ4Q>...</FAQ4Q><FAQ4R>...</FAQ4R>"""


def prompt_blog_listicle(sujet, kw_block, maillage_instructions):
    """FORMAT 2 : Listicle numéroté (~30% des articles).
    Structure : intro courte → 7-10 points numérotés avec sous-titre + paragraphe → conclusion."""
    return f"""Tu es expert SEO et rédacteur web pergolas France.
Tu rédiges un ARTICLE EN FORMAT LISTE NUMÉROTÉE (listicle) optimisé Discover sur : {sujet['titre']}
Mot-clé cible : {sujet['mot_cle']}
{kw_block}
{maillage_instructions}

OBJECTIF : listicle punchy, très mobile-friendly, qui cartonne sur Discover grâce à sa lisibilité.

{_regles_communes_blog(sujet)}

═══════════════════════════════════════════════════════
STRUCTURE SPÉCIFIQUE "LISTICLE NUMÉROTÉ" :
═══════════════════════════════════════════════════════
- Longueur : 900 à 1400 mots dans <CONTENU>
- Structure OBLIGATOIRE :
  * Une brève intro contextuelle : 1 <p> qui pose le problème ou l'enjeu
  * 7 à 10 points numérotés, CHACUN formaté AINSI :
    <div class="listicle-item">
      <div class="listicle-num">N</div>
      <div class="listicle-body">
        <h3>Titre court et percutant du point N</h3>
        <p>Paragraphe explicatif de 80-130 mots avec chiffres, exemples, conseils actionnables. Tu peux inclure <strong>mot-clés</strong> et <em>emphases</em>.</p>
      </div>
    </div>
  * Un dernier <p> de conclusion/synthèse qui récapitule

RÈGLES ESSENTIELLES :
- Numérotation de 1 à N (pas de sauts)
- Les titres <h3> doivent être COURTS et ACTIONNABLES (ex: "Vérifier l'orientation plein sud", "Négliger le drainage")
- Chaque point = un conseil ou une erreur/astuce INDÉPENDANTE
- Prix en euros (marché France 2026)
- Maillage interne dans un des paragraphes

Format STRICT :
<H1_OPTIMISE>titre 50-70 car. avec CHIFFRE (ex: "7 erreurs à éviter avec...") + mot-clé</H1_OPTIMISE>
<META>description 150-155 car. avec mot-clé + annonce du chiffre</META>
<INTRO>60-100 mots en HTML (<p>) : crochet + mot-clé + annonce des N points</INTRO>
<CONTENU>
<p>Intro contextuelle courte.</p>
<div class="listicle-item"><div class="listicle-num">1</div><div class="listicle-body"><h3>...</h3><p>...</p></div></div>
<div class="listicle-item"><div class="listicle-num">2</div><div class="listicle-body"><h3>...</h3><p>...</p></div></div>
[... 7 à 10 points au total ...]
<p>Conclusion/synthèse.</p>
</CONTENU>
<FAQ1Q>...</FAQ1Q><FAQ1R>...</FAQ1R>
<FAQ2Q>...</FAQ2Q><FAQ2R>...</FAQ2R>
<FAQ3Q>...</FAQ3Q><FAQ3R>...</FAQ3R>
<FAQ4Q>...</FAQ4Q><FAQ4R>...</FAQ4R>"""


def prompt_blog_comparatif(sujet, kw_block, maillage_instructions):
    """FORMAT 3 : Comparatif (~20% des articles).
    Structure : intro → présentation options → critères comparés → tableau HTML → verdict par profil."""
    return f"""Tu es expert SEO et rédacteur web pergolas France.
Tu rédiges un ARTICLE COMPARATIF (type "X ou Y ?") optimisé Discover sur : {sujet['titre']}
Mot-clé cible : {sujet['mot_cle']}
{kw_block}
{maillage_instructions}

OBJECTIF : comparatif qui aide à décider, avec tableau visuel + verdict selon profils utilisateurs.

{_regles_communes_blog(sujet)}

═══════════════════════════════════════════════════════
STRUCTURE SPÉCIFIQUE "COMPARATIF" :
═══════════════════════════════════════════════════════
- Longueur : 1200 à 1600 mots dans <CONTENU>
- Structure OBLIGATOIRE :
  1. <h2>Vue d'ensemble</h2> + <p> présentation rapide des 2 (ou 3) options comparées
  2. <h2>Option A : [nom]</h2> + <p> caractéristiques, avantages, inconvénients (150-200 mots)
  3. <h2>Option B : [nom]</h2> + <p> caractéristiques, avantages, inconvénients (150-200 mots)
  4. <h2>Comparatif détaillé</h2> + un TABLEAU HTML :
     <div class="compare-grid">
       <div class="compare-col compare-a">
         <h3>Option A</h3>
         <ul>
           <li><strong>Prix :</strong> fourchette €</li>
           <li><strong>Entretien :</strong> ...</li>
           <li><strong>Durée :</strong> ...</li>
           <li><strong>Installation :</strong> ...</li>
           <li>... (5-7 critères au total)</li>
         </ul>
       </div>
       <div class="compare-col compare-b">
         <h3>Option B</h3>
         <ul>...</ul>
       </div>
     </div>
  5. <h2>Notre verdict selon votre profil</h2> + 2-3 <p> :
     - Si vous cherchez X → option A
     - Si vous voulez Y → option B
  6. Un encart <div class="compare-verdict">TEXTE DU VERDICT GLOBAL EN UNE PHRASE</div>

- Chiffres précis et comparables (euros, années, mètres...)
- Maillage dans un des paragraphes

Format STRICT :
<H1_OPTIMISE>titre 50-70 car. avec mot-clé + "X ou Y ?" (ex: "Pergola bois ou alu : que choisir en 2026 ?")</H1_OPTIMISE>
<META>description 150-155 car. avec mot-clé + angle décision</META>
<INTRO>80-120 mots en HTML (<p>) : crochet + mot-clé + annonce du comparatif</INTRO>
<CONTENU>
<h2>Vue d'ensemble</h2><p>...</p>
<h2>Option A : ...</h2><p>...</p>
<h2>Option B : ...</h2><p>...</p>
<h2>Comparatif détaillé</h2>
<div class="compare-grid"><div class="compare-col compare-a">...</div><div class="compare-col compare-b">...</div></div>
<h2>Notre verdict selon votre profil</h2><p>...</p>
<div class="compare-verdict">Verdict en une phrase claire.</div>
</CONTENU>
<FAQ1Q>...</FAQ1Q><FAQ1R>...</FAQ1R>
<FAQ2Q>...</FAQ2Q><FAQ2R>...</FAQ2R>
<FAQ3Q>...</FAQ3Q><FAQ3R>...</FAQ3R>
<FAQ4Q>...</FAQ4Q><FAQ4R>...</FAQ4R>"""


def prompt_blog_qr(sujet, kw_block, maillage_instructions):
    """FORMAT 4 : Q/R approfondi (~15% des articles).
    Structure : intro → 6-8 questions/réponses détaillées → synthèse finale."""
    return f"""Tu es expert SEO et rédacteur web pergolas France.
Tu rédiges un ARTICLE EN FORMAT QUESTIONS/RÉPONSES APPROFONDI sur : {sujet['titre']}
Mot-clé cible : {sujet['mot_cle']}
{kw_block}
{maillage_instructions}

OBJECTIF : article qui répond de façon claire et structurée aux questions courantes sur le sujet.
Idéal pour : réglementation, démarches administratives, prix, assurance, permis.

{_regles_communes_blog(sujet)}

═══════════════════════════════════════════════════════
STRUCTURE SPÉCIFIQUE "QUESTIONS/RÉPONSES" :
═══════════════════════════════════════════════════════
- Longueur : 1100 à 1500 mots dans <CONTENU>
- Structure OBLIGATOIRE :
  1. <h2>Introduction</h2> + <p> contexte et enjeux (100-150 mots)
  2. 6 à 8 blocs Q/R, CHACUN formaté AINSI :
     <div class="qr-item">
       <h3 class="qr-question">La question posée ici ?</h3>
       <div class="qr-answer">
         <p>Réponse claire et directe en 100-150 mots, avec chiffres si pertinent. Tu peux inclure <strong>mots-clés</strong> et des <ul><li>points précis</li></ul> si besoin.</p>
       </div>
     </div>
  3. <h2>En résumé</h2> + <p> synthèse actionnable (80-120 mots)

RÈGLES ESSENTIELLES :
- Les questions <h3 class="qr-question"> doivent être DES QUESTIONS RÉELLES (avec ?)
- Réponses directes, pas de remplissage, chiffres concrets
- Chaque question aborde un aspect DIFFÉRENT du sujet
- Au moins 1 question doit contenir le mot-clé cible
- Maillage interne dans une des réponses

Format STRICT :
<H1_OPTIMISE>titre 50-70 car. avec mot-clé (ex: "Permis pergola : 8 questions essentielles 2026")</H1_OPTIMISE>
<META>description 150-155 car. avec mot-clé + promesse de réponses claires</META>
<INTRO>80-120 mots en HTML (<p>) : crochet + mot-clé + annonce du Q/R</INTRO>
<CONTENU>
<h2>Introduction</h2><p>...</p>
<div class="qr-item"><h3 class="qr-question">...?</h3><div class="qr-answer"><p>...</p></div></div>
<div class="qr-item"><h3 class="qr-question">...?</h3><div class="qr-answer"><p>...</p></div></div>
[... 6 à 8 blocs Q/R ...]
<h2>En résumé</h2><p>...</p>
</CONTENU>
<FAQ1Q>...</FAQ1Q><FAQ1R>...</FAQ1R>
<FAQ2Q>...</FAQ2Q><FAQ2R>...</FAQ2R>
<FAQ3Q>...</FAQ3Q><FAQ3R>...</FAQ3R>
<FAQ4Q>...</FAQ4Q><FAQ4R>...</FAQ4R>"""


def prompt_blog_cas_pratique(sujet, kw_block, maillage_instructions):
    """FORMAT 5 : Cas pratique / étude de cas (~10% des articles).
    Structure : situation initiale → problème → solution → résultats + chiffres → leçons.
    Format TRÈS humain, difficile à détecter comme IA."""
    return f"""Tu es expert SEO et rédacteur web pergolas France.
Tu rédiges un ARTICLE CAS PRATIQUE / ÉTUDE DE CAS sur : {sujet['titre']}
Mot-clé cible : {sujet['mot_cle']}
{kw_block}
{maillage_instructions}

OBJECTIF : article narratif concret qui raconte un cas RÉEL (ou réaliste) de propriétaire français.
Format "récit journalistique" : humain, concret, chiffré, qui inspire confiance.

{_regles_communes_blog(sujet)}

═══════════════════════════════════════════════════════
STRUCTURE SPÉCIFIQUE "CAS PRATIQUE" :
═══════════════════════════════════════════════════════
- Longueur : 1100 à 1500 mots dans <CONTENU>
- Ton : narratif, semi-personnel, à la 3e personne. Style journalistique de reportage.
- Invente un profil FICTIF MAIS RÉALISTE (prénom + région + contexte de vie) :
  * Exemples : "Thomas, 42 ans, propriétaire d'une maison des années 80 près de Lyon"
  * "Sophie et Julien, jeune couple installé à Rennes dans un pavillon de 2015"
- PAS de "je" ni de "nous" — rester descriptif/journalistique

Structure OBLIGATOIRE :
  1. <h2>Le contexte : [situation de départ]</h2>
     <p>Qui, où, quand, quel besoin initial. 120-180 mots avec chiffres concrets (surface, budget, type de maison, contrainte).</p>
  2. <h2>Le problème / la contrainte à résoudre</h2>
     <p>Quelle difficulté précise a poussé à agir. 120-180 mots.</p>
  3. <h2>La solution retenue</h2>
     <p>Quel choix (matériau, dimensions, prestataire) et POURQUOI ce choix. 150-200 mots.</p>
     <div class="cas-infos">
       <div class="cas-info-item"><strong>Solution :</strong> <span>...</span></div>
       <div class="cas-info-item"><strong>Budget total :</strong> <span>... €</span></div>
       <div class="cas-info-item"><strong>Délai :</strong> <span>... semaines</span></div>
       <div class="cas-info-item"><strong>Prestataire :</strong> <span>artisan local / fabricant / auto-installation</span></div>
     </div>
  4. <h2>Le déroulement du projet</h2>
     <p>Étapes concrètes, avec éventuellement quelques surprises rencontrées. 150-200 mots.</p>
  5. <h2>Les résultats concrets</h2>
     <p>Chiffres précis : gain de confort, économies, surface utilisable, etc. 120-180 mots.</p>
  6. <h2>Les leçons à retenir pour votre projet</h2>
     <ul>
       <li>Conseil 1 tiré du cas</li>
       <li>Conseil 2 tiré du cas</li>
       <li>... (4-6 enseignements actionnables)</li>
     </ul>

- Prix en euros (marché France 2026), précis
- Maillage dans un des paragraphes

Format STRICT :
<H1_OPTIMISE>titre 50-70 car. avec mot-clé + angle "cas concret" (ex: "Pergola 20m² à Lyon : retour d'expérience et budget 2026")</H1_OPTIMISE>
<META>description 150-155 car. avec mot-clé + promesse chiffres concrets</META>
<INTRO>80-120 mots en HTML (<p>) : présente brièvement le cas + mot-clé dans 1ère phrase</INTRO>
<CONTENU>
<h2>Le contexte : ...</h2><p>...</p>
<h2>Le problème / la contrainte à résoudre</h2><p>...</p>
<h2>La solution retenue</h2><p>...</p>
<div class="cas-infos">
  <div class="cas-info-item"><strong>Solution :</strong> <span>...</span></div>
  <div class="cas-info-item"><strong>Budget total :</strong> <span>... €</span></div>
  <div class="cas-info-item"><strong>Délai :</strong> <span>... semaines</span></div>
  <div class="cas-info-item"><strong>Prestataire :</strong> <span>...</span></div>
</div>
<h2>Le déroulement du projet</h2><p>...</p>
<h2>Les résultats concrets</h2><p>...</p>
<h2>Les leçons à retenir pour votre projet</h2><ul><li>...</li>...</ul>
</CONTENU>
<FAQ1Q>...</FAQ1Q><FAQ1R>...</FAQ1R>
<FAQ2Q>...</FAQ2Q><FAQ2R>...</FAQ2R>
<FAQ3Q>...</FAQ3Q><FAQ3R>...</FAQ3R>
<FAQ4Q>...</FAQ4Q><FAQ4R>...</FAQ4R>"""


def prompt_blog_saisonnier(sujet, kw_block, maillage_instructions):
    """FORMAT 6 : Article saisonnier (~10% des articles).
    Structure : contexte temporel → pourquoi c'est important maintenant → actions par ordre d'urgence → planning.
    Dimension temporelle explicite = anti-IA (contenu contextualisé)."""
    # Détermination de la saison en cours (aide Claude à contextualiser)
    mois_actuel = datetime.now().month
    saison = (
        "printemps" if 3 <= mois_actuel <= 5 else
        "été"       if 6 <= mois_actuel <= 8 else
        "automne"   if 9 <= mois_actuel <= 11 else
        "hiver"
    )
    return f"""Tu es expert SEO et rédacteur web pergolas France.
Tu rédiges un ARTICLE SAISONNIER optimisé Discover sur : {sujet['titre']}
Mot-clé cible : {sujet['mot_cle']}
Saison actuelle en France : {saison} 2026 (mois : {mois_actuel})
{kw_block}
{maillage_instructions}

OBJECTIF : article contextualisé dans le TEMPS (saison, moment de l'année), qui donne envie d'agir MAINTENANT.
Format idéal pour Discover : Google adore les articles "frais" avec dimension temporelle.

{_regles_communes_blog(sujet)}

═══════════════════════════════════════════════════════
STRUCTURE SPÉCIFIQUE "SAISONNIER" :
═══════════════════════════════════════════════════════
- Longueur : 1100 à 1500 mots dans <CONTENU>
- Ton : contextualisé, actionnable, avec une vraie urgence temporelle
- INTÈGRE naturellement des références à la saison actuelle ({saison}), aux mois, aux températures France

Structure OBLIGATOIRE :
  1. <div class="saison-badge">
       <span class="saison-label">{saison.capitalize()} 2026</span>
       <span class="saison-message">Le moment clé pour agir</span>
     </div>
  2. <h2>Pourquoi {saison} est LA période critique pour votre pergola</h2>
     <p>Explique les spécificités de la saison actuelle (météo France, conditions, contraintes).
     120-180 mots. Si c'est une saison transitoire, explique ce qui se joue maintenant.</p>
  3. <h2>Les 3 actions prioritaires à faire avant [moment précis]</h2>
     <p>Introduction courte.</p>
     <div class="saison-action">
       <div class="saison-action-num">1</div>
       <div class="saison-action-body">
         <h3>Action prioritaire 1</h3>
         <p>80-130 mots : quoi faire exactement, avec chiffres et délais.</p>
         <div class="saison-urgence"><strong>À faire avant :</strong> [mois/semaine précise]</div>
       </div>
     </div>
     [... répéter pour action 2 et action 3 ...]
  4. <h2>Le planning idéal sur les prochaines semaines</h2>
     <p>Présente un calendrier pratique.</p>
     <ul>
       <li><strong>Cette semaine :</strong> ...</li>
       <li><strong>Dans 2 semaines :</strong> ...</li>
       <li><strong>Avant fin [mois] :</strong> ...</li>
       <li><strong>D'ici [saison suivante] :</strong> ...</li>
     </ul>
  5. <h2>Les erreurs classiques en {saison}</h2>
     <p>3-4 erreurs fréquentes à cette période. 150 mots.</p>
  6. <h2>Budget à prévoir en {saison} 2026</h2>
     <p>Fourchettes de prix contextualisées à la saison. 120-180 mots.</p>

- Références au calendrier, au climat France, aux prix actuels 2026
- Maillage dans un des paragraphes

Format STRICT :
<H1_OPTIMISE>titre 50-70 car. avec mot-clé + saison/urgence (ex: "Pergola au {saison} : les 3 vérifications essentielles 2026")</H1_OPTIMISE>
<META>description 150-155 car. avec mot-clé + urgence saisonnière</META>
<INTRO>80-120 mots en HTML (<p>) : crochet saisonnier + mot-clé + annonce des actions</INTRO>
<CONTENU>
<div class="saison-badge"><span class="saison-label">{saison.capitalize()} 2026</span><span class="saison-message">Le moment clé pour agir</span></div>
<h2>Pourquoi {saison} est LA période critique pour votre pergola</h2><p>...</p>
<h2>Les 3 actions prioritaires à faire avant [moment]</h2><p>...</p>
<div class="saison-action"><div class="saison-action-num">1</div><div class="saison-action-body"><h3>...</h3><p>...</p><div class="saison-urgence"><strong>À faire avant :</strong> ...</div></div></div>
<div class="saison-action"><div class="saison-action-num">2</div><div class="saison-action-body"><h3>...</h3><p>...</p><div class="saison-urgence"><strong>À faire avant :</strong> ...</div></div></div>
<div class="saison-action"><div class="saison-action-num">3</div><div class="saison-action-body"><h3>...</h3><p>...</p><div class="saison-urgence"><strong>À faire avant :</strong> ...</div></div></div>
<h2>Le planning idéal sur les prochaines semaines</h2><ul><li><strong>Cette semaine :</strong> ...</li>...</ul>
<h2>Les erreurs classiques en {saison}</h2><p>...</p>
<h2>Budget à prévoir en {saison} 2026</h2><p>...</p>
</CONTENU>
<FAQ1Q>...</FAQ1Q><FAQ1R>...</FAQ1R>
<FAQ2Q>...</FAQ2Q><FAQ2R>...</FAQ2R>
<FAQ3Q>...</FAQ3Q><FAQ3R>...</FAQ3R>
<FAQ4Q>...</FAQ4Q><FAQ4R>...</FAQ4R>"""


def build_prompt_format(format_blog, sujet, kw_block, maillage_instructions):
    """Dispatcher : choisit le prompt selon le format tiré au sort."""
    fn = {
        "guide":        prompt_blog_guide,
        "listicle":     prompt_blog_listicle,
        "comparatif":   prompt_blog_comparatif,
        "qr":           prompt_blog_qr,
        "cas_pratique": prompt_blog_cas_pratique,
        "saisonnier":   prompt_blog_saisonnier,
    }.get(format_blog, prompt_blog_guide)
    return fn(sujet, kw_block, maillage_instructions)


def css_formats_blog():
    """CSS commun + styles spécifiques aux 4 formats (listicle, comparatif, qr).
    Injecté dans le <head> des pages blog pour que les formats rendent correctement."""
    return '''
  <style>
    /* ─── Listicle : numéros colorés ─── */
    .listicle-item{display:flex;gap:16px;margin:22px 0;align-items:flex-start;}
    .listicle-num{flex-shrink:0;width:44px;height:44px;border-radius:50%;
      background:#2d5a3d;color:#fff;display:flex;align-items:center;justify-content:center;
      font-family:Georgia,serif;font-weight:500;font-size:1.3rem;}
    .listicle-body{flex:1;min-width:0;}
    .listicle-body h3{margin:0 0 6px;color:#2d5a3d;font-family:Georgia,serif;
      font-size:1.15rem;font-weight:500;line-height:1.3;}
    .listicle-body p{margin:0;line-height:1.65;}

    /* ─── Comparatif : tableau 2 colonnes + verdict ─── */
    .compare-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:20px 0;}
    .compare-col{background:#fafaf7;border:1px solid #e8e8e0;padding:18px;border-radius:10px;}
    .compare-col h3{margin:0 0 12px;color:#2d5a3d;font-family:Georgia,serif;
      font-size:1.15rem;font-weight:500;padding-bottom:8px;border-bottom:2px solid #c5a572;}
    .compare-col ul{padding-left:18px;margin:0;}
    .compare-col li{margin-bottom:8px;font-size:.95rem;line-height:1.5;}
    .compare-verdict{background:#c5a572;color:#fff;padding:16px 20px;border-radius:10px;
      margin:20px 0;font-family:Georgia,serif;font-size:1.05rem;font-weight:500;
      text-align:center;line-height:1.5;}
    @media (max-width:640px){
      .compare-grid{grid-template-columns:1fr;}
    }

    /* ─── Q/R : questions en vert, réponses sur fond clair ─── */
    .qr-item{margin:20px 0;border-left:3px solid #2d5a3d;padding:2px 0 2px 18px;}
    .qr-question{margin:0 0 10px;color:#2d5a3d;font-family:Georgia,serif;
      font-size:1.18rem;font-weight:500;line-height:1.35;}
    .qr-answer{background:#fafaf7;padding:14px 18px;border-radius:8px;}
    .qr-answer p{margin:0 0 10px;line-height:1.65;}
    .qr-answer p:last-child{margin-bottom:0;}
    .qr-answer ul{margin:8px 0;padding-left:20px;}
    .qr-answer li{margin-bottom:4px;line-height:1.55;}

    /* ─── Cas pratique : encart infos-clés ─── */
    .cas-infos{background:#fafaf7;border:1px solid #e8e8e0;border-radius:10px;
      padding:20px;margin:20px 0;display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;}
    .cas-info-item{display:flex;flex-direction:column;padding:10px 14px;
      background:#fff;border-radius:6px;border-left:3px solid #c5a572;}
    .cas-info-item strong{color:#2d5a3d;font-size:.85rem;text-transform:uppercase;
      letter-spacing:.5px;margin-bottom:4px;font-weight:500;}
    .cas-info-item span{color:#222;font-family:Georgia,serif;font-size:1.05rem;}

    /* ─── Saisonnier : badge saison + actions numérotées avec urgence ─── */
    .saison-badge{display:flex;align-items:center;gap:14px;background:#2d5a3d;color:#fff;
      padding:16px 20px;border-radius:10px;margin:16px 0 24px;flex-wrap:wrap;}
    .saison-label{background:#c5a572;color:#fff;padding:6px 14px;border-radius:6px;
      font-weight:500;font-size:.95rem;letter-spacing:.5px;text-transform:uppercase;}
    .saison-message{font-family:Georgia,serif;font-size:1.1rem;font-style:italic;}
    .saison-action{display:flex;gap:16px;margin:18px 0;align-items:flex-start;
      background:#fafaf7;padding:16px 18px;border-radius:10px;border-left:4px solid #c5a572;}
    .saison-action-num{flex-shrink:0;width:44px;height:44px;border-radius:50%;
      background:#c5a572;color:#fff;display:flex;align-items:center;justify-content:center;
      font-family:Georgia,serif;font-weight:500;font-size:1.3rem;}
    .saison-action-body{flex:1;min-width:0;}
    .saison-action-body h3{margin:0 0 8px;color:#2d5a3d;font-family:Georgia,serif;
      font-size:1.15rem;font-weight:500;line-height:1.3;}
    .saison-action-body p{margin:0 0 10px;line-height:1.6;}
    .saison-urgence{background:#fff;border:1px dashed #c5a572;padding:8px 12px;
      border-radius:6px;font-size:.92rem;color:#2d5a3d;margin-top:8px;}
    .saison-urgence strong{color:#c5a572;}
  </style>'''


# ─── ARTICLE DE BLOG ──────────────────────────────────────
def generer_article_blog(archi, keywords=None, comments_config=None):
    sujets_file = Path("sujets.json")
    if not sujets_file.exists():
        print("❌ sujets.json introuvable"); return

    sujets   = json.loads(sujets_file.read_text(encoding="utf-8"))
    traites_file = Path("sujets_traites.json")
    traites  = json.loads(traites_file.read_text()) if traites_file.exists() else []
    restants = [s for s in sujets if s["slug"] not in traites] or sujets

    sujet = random.choice(restants)
    traites.append(sujet["slug"])
    traites_file.write_text(json.dumps(traites, ensure_ascii=False))

    # Pilier parent
    pilier_parent     = None
    secondaire_parent = None
    for p in archi["piliers"]:
        if p["id"] == sujet.get("pilier_id"):
            pilier_parent = p
            for s in p["secondaires"]:
                if s["slug"] == sujet.get("secondaire_slug"):
                    secondaire_parent = s
            break

    img = get_image(prompt_image_blog(sujet),
                    modele="schnell",
                    chemin_local=f"images/blog/{sujet['slug']}.webp")

    # Ancres diversifiées — URLs absolues
    ancre_pilier = ""
    ancre_sec    = ""
    url_pilier   = ""
    url_sec      = ""
    if pilier_parent and comments_config:
        ancre_pilier = ancre_aleatoire(pilier_parent['id'], comments_config)
        url_pilier   = f"/{pilier_parent['slug']}.html"
    if secondaire_parent and pilier_parent:
        ancre_sec = secondaire_parent.get('mot_cle', secondaire_parent['titre'])
        url_sec   = f"/{pilier_parent['id']}/{secondaire_parent['slug']}.html"

    # KW liés
    kw_block = ""
    if keywords and sujet.get('pilier_id') in keywords:
        data   = keywords[sujet['pilier_id']]
        termes = sujet.get('mot_cle', '').lower().split()
        kw_lies = [
            kw for kw in data.get('secondaires', []) + data.get('longue_traine', [])
            if any(t in kw['kw'].lower() for t in termes if len(t) > 3)
        ][:8]
        if kw_lies:
            kw_block = "\nMots-clés SEO à intégrer :\n" + "\n".join(
                f"  - {kw['kw']} ({kw['vol']:,}/mois)" for kw in kw_lies
            ) + "\n"

    # Instructions maillage contextuel
    maillage_instructions = ""
    if url_pilier and ancre_pilier:
        maillage_instructions += f"""
MAILLAGE INTERNE OBLIGATOIRE dans le corps de l'article (pas à la fin) :
1. Intègre naturellement dans un paragraphe <p> un lien HTML vers le guide pilier :
   <a href="{url_pilier}">{ancre_pilier}</a>
   L'ancre DOIT être exactement : "{ancre_pilier}"
   Le lien doit être dans une phrase qui parle de ce sujet, pas isolé."""
    if url_sec and ancre_sec:
        maillage_instructions += f"""
2. Intègre naturellement dans un autre paragraphe <p> un lien vers la page secondaire :
   <a href="{url_sec}">{ancre_sec}</a>
   L'ancre DOIT être exactement : "{ancre_sec}"
   Le lien doit être dans une phrase contextuelle pertinente."""

    # Choix d'un format éditorial (guide/listicle/comparatif/qr) pour varier la structure
    # et éviter toute signature "content farm IA" (protection anti-update Discover).
    format_blog = choisir_format_blog(sujet)
    print(f"  🎨 Format choisi : {format_blog}")
    prompt = build_prompt_format(format_blog, sujet, kw_block, maillage_instructions)

    texte = appeler_claude(prompt, max_tokens=6000)
    contenu_brut = extraire_balise(texte, "CONTENU") or ""
    nb_mots = compter_mots_html(contenu_brut)

    if nb_mots < 700:
        print(f"  ⚠️ Article blog trop court ({nb_mots} mots), nouvel essai...")
        texte = appeler_claude(prompt, max_tokens=6000)
        contenu_brut = extraire_balise(texte, "CONTENU") or ""
        nb_mots = compter_mots_html(contenu_brut)

    contenu = nettoyer_markdown_vers_html(contenu_brut)
    meta    = extraire_balise(texte, "META") or sujet["titre"]
    intro   = nettoyer_markdown_vers_html(extraire_balise(texte, "INTRO") or "")
    if intro and "<p" not in intro:
        intro = f"<p>{intro}</p>"

    # Titre optimisé SEO+Discover généré par Claude (fallback : titre brut si absent)
    titre_optimise = extraire_balise(texte, "H1_OPTIMISE") or sujet["titre"]
    # Sécurité : tronquer si Claude a dépassé les 80 caractères
    if len(titre_optimise) > 80:
        titre_optimise = titre_optimise[:77].rsplit(" ", 1)[0] + "…"

    qrs      = []
    faq_html = ""
    for i in range(1, 5):
        q = extraire_balise(texte, f"FAQ{i}Q")
        r = extraire_balise(texte, f"FAQ{i}R")
        if q and r:
            r_clean = nettoyer_markdown_vers_html(r)
            qrs.append({"q": q, "r": r})
            faq_html += f'<div class="faq-item"><button class="faq-question">{q}</button><div class="faq-reponse">{r_clean}</div></div>\n'

    date_iso = datetime.now().strftime("%Y-%m-%d")

    # Articles similaires (chargés depuis articles.json existant)
    articles_existants = charger_articles()
    similaires_html    = generer_articles_similaires(
        sujet["slug"], sujet.get("pilier_id", ""), articles_existants
    )

    # Schemas — URLs absolues mises à jour
    breadcrumb_items = [{"name": "Accueil", "url": f"{SITE_URL}/"}]
    if pilier_parent:
        breadcrumb_items.append({
            "name": pilier_parent["titre"],
            "url": f"{SITE_URL}/{pilier_parent['slug']}.html"
        })
    breadcrumb_items.append({
        "name": titre_optimise,
        "url": f"{SITE_URL}/blog/{sujet['slug']}.html"
    })

    breadcrumb_schema = schema_breadcrumb(breadcrumb_items)
    faq_schema        = schema_faq(qrs)
    article_schema    = schema_article(
        titre_optimise, meta, img["url"],
        date_published=date_iso, date_modified=date_iso
    )

    # CSS spécifique aux pages blog (typo + maillage articles + styles des 6 formats éditoriaux)
    css_blog = '''
  <style>
    .article-body{max-width:820px;margin:0 auto;line-height:1.75;color:#222;font-size:1.02rem;}
    .article-body h2{font-family:Georgia,serif;color:var(--vert,#2d5a3d);font-size:1.45rem;margin:30px 0 14px;padding-bottom:8px;border-bottom:2px solid #e8e8e0;}
    .article-body h3{color:#2d5a3d;font-size:1.15rem;margin:22px 0 10px;}
    .article-body p{margin:0 0 14px;}
    .article-body ul,.article-body ol{margin:0 0 16px;padding-left:22px;}
    .article-body li{margin:0 0 6px;}
    .article-body strong{color:#2d5a3d;}
    .article-body a{color:#2d5a3d;text-decoration:underline;}
    .intro{font-size:1.08rem;line-height:1.7;color:#333;margin:10px 0 20px;}
    .intro p{margin:0 0 10px;}

    /* Maillage articles similaires (même style que sur les secondaires) */
    /* Hérite de la largeur de .container — pas de max-width propre */
    .maillage-articles{margin:50px 0;}
    .maillage-articles h2{font-family:Georgia,serif;color:var(--vert,#2d5a3d);font-size:1.6rem;text-align:center;margin:0 0 26px;}
    .maillage-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:20px;}
    .maillage-card{display:flex;flex-direction:column;background:#fff;border:1px solid #e8e8e0;border-radius:8px;overflow:hidden;transition:transform .2s,box-shadow .2s;}
    .maillage-card:hover{transform:translateY(-2px);box-shadow:0 8px 24px rgba(45,90,61,.12);}
    .maillage-titre{padding:14px 14px 10px;font-weight:600;color:#2d5a3d;text-decoration:none;font-size:1rem;line-height:1.35;display:flex;align-items:flex-start;min-height:62px;box-sizing:border-box;}
    .maillage-titre:hover{text-decoration:underline;}
    .maillage-img-link{display:block;margin-top:auto;}
    .maillage-img{width:100%;height:140px;object-fit:cover;display:block;background:#f0ede5;}
  </style>''' + css_formats_blog()

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{titre_optimise} | {SITE_NOM}</title>
  <meta name="description" content="{meta}">
  {meta_commune()}
  {meta_sociales(
    titre=titre_optimise,
    description=meta,
    image_url=img["url"],
    url_page=f"{SITE_URL}/blog/{sujet['slug']}.html",
    type_og="article"
  )}
  <link rel="canonical" href="{SITE_URL}/blog/{sujet['slug']}.html">
  <!-- Preload de l'image LCP responsive : le navigateur télécharge la bonne taille selon l'écran -->
  {_preload_responsive(img['url'], role="article")}
  {lien_css()}
{css_blog}
  <script type="application/ld+json">{article_schema}</script>
  <script type="application/ld+json">{breadcrumb_schema}</script>
  {f'<script type="application/ld+json">{faq_schema}</script>' if faq_schema else ''}
</head>
<body>
  {construire_header(archi, "blog", sujet.get('pilier_id'))}
  <main class="container">
    <nav class="fil-ariane">
      <a href="/">Accueil</a> ›
      {f"<a href='/{pilier_parent['slug']}.html'>{pilier_parent['titre']}</a> ›" if pilier_parent else ""}
      <span>{titre_optimise}</span>
    </nav>
    <div class="page-layout">
      <article class="contenu-principal">
        <span class="categorie">{sujet.get('categorie','Blog')}</span>
        <h1>{titre_optimise}</h1>
        {bloc_date_auteur_top(date_iso, date_iso)}
        <div class="intro">{intro}</div>
        {img_responsive(img['url'], titre_optimise, role="article", loading="eager", fetchpriority="high", width=1200, height=800, classe="article-img")}
        {bloc_adsense(ADSENSE_SLOT_MILIEU, "inArticle")}
        <div class="article-body">{contenu}</div>
        <div class="faq-section">
          <h2>Questions fréquentes</h2>{faq_html}
        </div>
        {bloc_auteur_fin_article()}
        {similaires_html}
        {bloc_adsense(ADSENSE_SLOT_BAS, "horizontal")}
        <div class="commentaires-section" id="commentaires">
          <h2>Commentaires</h2>
          <div id="liste-commentaires"><!-- Commentaires chargés dynamiquement --></div>
        </div>
      </article>
      <aside class="sidebar">
        <div class="widget" id="widget-recents"></div>
        {bloc_adsense(ADSENSE_SLOT_SIDEBAR, "sidebar")}
      </aside>
    </div>
  </main>
  {construire_footer("blog")}
  <script>
    const PILIER_ID  = "{sujet.get('pilier_id','')}";
    const ARTICLE_SLUG = "{sujet['slug']}";
  </script>
  {lien_js()}
  {banner_cookies()}
</body></html>"""

    Path(f"blog/{sujet['slug']}.html").write_text(html, encoding="utf-8")

    # Mise à jour articles.json
    index_file = Path("articles.json")
    articles   = json.loads(index_file.read_text(encoding="utf-8")) if index_file.exists() else []

    # Thumb = la même image que celle de l'article (stockée en local, donc permanente)
    # Le navigateur redimensionnera naturellement via l'attribut CSS .card-image
    articles.insert(0, {
        "slug": sujet["slug"],
        "titre": titre_optimise,
        "categorie": sujet.get("categorie","Blog"),
        "description": meta,
        "date": date_iso,
        "thumb": img.get("url",""),
        "pilier_id": sujet.get("pilier_id",""),
        "secondaire_slug": sujet.get("secondaire_slug","")
    })
    articles = articles[:500]
    index_file.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")

    # Régénérer page secondaire parente (maillage statique)
    if secondaire_parent and pilier_parent:
        print(f"  🔄 Mise à jour maillage page secondaire...")
        generer_page_secondaire(secondaire_parent, pilier_parent, archi, keywords, articles)

    # Initialiser le planning de commentaires
    initialiser_planning_commentaires(sujet, articles)

    generer_page_blog(archi, articles)
    generer_accueil(archi, articles, regenerer_images=False)  # miniatures home à jour, slider cached
    generer_sitemap(archi, articles)
    generer_feed_rss(articles)  # Flux RSS mis à jour avec le nouvel article
    ping_google_sitemap()
    print(f"✅ blog/{sujet['slug']}.html")

# ─── PLANNING COMMENTAIRES ────────────────────────────────
def initialiser_planning_commentaires(sujet, articles):
    """Crée le planning de commentaires pour un nouvel article."""
    from datetime import timedelta

    planning_file = Path("comments_planning.json")
    planning      = json.loads(planning_file.read_text(encoding="utf-8")) if planning_file.exists() else {}

    if sujet["slug"] in planning:
        return  # Déjà planifié

    # Déterminer la popularité selon le volume du mot-clé
    vol = sujet.get("volume", 0)
    if vol > 5000:
        popularite = "tres_haute"; min_c, max_c = 5, 8; prob_zero = 0.03
    elif vol > 1000:
        popularite = "haute";      min_c, max_c = 3, 5; prob_zero = 0.10
    elif vol > 500:
        popularite = "moyenne";    min_c, max_c = 1, 3; prob_zero = 0.30
    elif vol > 100:
        popularite = "faible";     min_c, max_c = 0, 2; prob_zero = 0.50
    else:
        popularite = "tres_faible";min_c, max_c = 0, 1; prob_zero = 0.70

    # Tirage aléatoire : cet article aura-t-il des commentaires ?
    if random.random() < prob_zero:
        planning[sujet["slug"]] = {"popularite": popularite, "nb_commentaires": 0, "planning": []}
        planning_file.write_text(json.dumps(planning, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    nb_total    = random.randint(min_c, max_c)
    date_pub    = datetime.strptime(sujet.get("date", datetime.now().strftime("%Y-%m-%d")), "%Y-%m-%d")
    commentaires = []

    # Charger les profils
    config   = charger_comments_config()
    profils  = config.get("profils", [])
    types_c  = config.get("types_commentaires", ["question_pratique"])
    
    # Sélectionner des profils uniques pour cet article
    profils_article = random.sample(profils, min(nb_total * 2, len(profils)))
    
    date_courante = date_pub
    idx_profil    = 0

    for i in range(nb_total):
        # Délai avant ce commentaire
        if i == 0:
            delai = random.randint(5, 14)
        else:
            delai = random.randint(2, 7)
        
        date_courante += timedelta(days=delai + random.randint(0, 2))
        profil = profils_article[idx_profil % len(profils_article)]
        idx_profil += 1

        commentaire = {
            "id": f"c{i}",
            "type": "commentaire",
            "profil": profil["nom"],
            "region": profil["region"],
            "style": profil["style"],
            "type_message": random.choice(types_c),
            "date_prevue": date_courante.strftime("%Y-%m-%d"),
            "statut": "pending",
            "reponses": []
        }

        # Ce commentaire aura-t-il une réponse ?
        if random.random() > 0.40:
            delai_rep = random.randint(1, 4)
            date_rep  = date_courante + timedelta(days=delai_rep)
            profil_rep = profils_article[idx_profil % len(profils_article)]
            idx_profil += 1

            reponse = {
                "id": f"r{i}_0",
                "type": "reponse",
                "profil": profil_rep["nom"],
                "region": profil_rep["region"],
                "style": profil_rep["style"],
                "type_message": random.choice(["complement_information", "retour_experience_positif", "conseil_materiau"]),
                "date_prevue": date_rep.strftime("%Y-%m-%d"),
                "statut": "pending"
            }

            # Contre-réponse ?
            if random.random() > 0.65:
                delai_cr  = random.randint(1, 3)
                date_cr   = date_rep + timedelta(days=delai_cr)
                profil_cr = profils_article[idx_profil % len(profils_article)]
                idx_profil += 1

                reponse["contre_reponse"] = {
                    "id": f"cr{i}_0",
                    "type": "contre_reponse",
                    "profil": profil_cr["nom"],
                    "region": profil_cr["region"],
                    "style": profil_cr["style"],
                    "type_message": "remerciement_avec_question",
                    "date_prevue": date_cr.strftime("%Y-%m-%d"),
                    "statut": "pending"
                }

            commentaire["reponses"].append(reponse)
        
        commentaires.append(commentaire)

    planning[sujet["slug"]] = {
        "popularite": popularite,
        "titre": sujet["titre"],
        "pilier_id": sujet.get("pilier_id",""),
        "nb_commentaires": nb_total,
        "planning": commentaires
    }

    planning_file.write_text(json.dumps(planning, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  📅 Planning: {nb_total} commentaires prévus ({popularite})")

# ─── GÉNÉRATION COMMENTAIRES (workflow quotidien) ──────────
def generer_commentaires_du_jour(archi):
    """Appelé quotidiennement par comments.yml"""
    planning_file = Path("comments_planning.json")
    if not planning_file.exists():
        print("Aucun planning trouvé"); return

    planning = json.loads(planning_file.read_text(encoding="utf-8"))
    comments_file = Path("comments.json")
    comments_data = json.loads(comments_file.read_text(encoding="utf-8")) if comments_file.exists() else {}
    
    aujourd_hui = datetime.now().strftime("%Y-%m-%d")
    articles    = charger_articles()
    modifie     = False

    for slug, data in planning.items():
        for item in data.get("planning", []):
            if item["statut"] != "pending":
                continue
            if item["date_prevue"] > aujourd_hui:
                continue

            # Générer ce commentaire
            art_info = next((a for a in articles if a["slug"] == slug), {})
            texte_c  = generer_texte_commentaire(item, data["titre"], art_info)
            
            if slug not in comments_data:
                comments_data[slug] = []

            comment_obj = {
                "id": item["id"],
                "auteur": item["profil"],
                "region": item["region"],
                "date": item["date_prevue"],
                "texte": texte_c,
                "reponses": []
            }

            # Traiter les réponses
            for rep in item.get("reponses", []):
                if rep["statut"] == "pending" and rep["date_prevue"] <= aujourd_hui:
                    texte_r = generer_texte_commentaire(rep, data["titre"], art_info, parent_texte=texte_c)
                    rep_obj = {
                        "id": rep["id"],
                        "auteur": rep["profil"],
                        "region": rep["region"],
                        "date": rep["date_prevue"],
                        "texte": texte_r,
                        "reponses": []
                    }
                    # Contre-réponse
                    cr = rep.get("contre_reponse", {})
                    if cr and cr.get("statut") == "pending" and cr.get("date_prevue", "9999") <= aujourd_hui:
                        texte_cr = generer_texte_commentaire(cr, data["titre"], art_info, parent_texte=texte_r)
                        rep_obj["reponses"].append({
                            "id": cr["id"],
                            "auteur": cr["profil"],
                            "region": cr["region"],
                            "date": cr["date_prevue"],
                            "texte": texte_cr
                        })
                        cr["statut"] = "done"

                    comment_obj["reponses"].append(rep_obj)
                    rep["statut"] = "done"

            comments_data[slug].append(comment_obj)
            item["statut"] = "done"
            modifie = True
            print(f"  💬 Commentaire généré pour {slug} par {item['profil']}")

            # Régénérer la page blog avec les commentaires
            regenerer_blog_avec_commentaires(slug, comments_data, archi, articles)

    if modifie:
        planning_file.write_text(json.dumps(planning, ensure_ascii=False, indent=2), encoding="utf-8")
        comments_file.write_text(json.dumps(comments_data, ensure_ascii=False, indent=2), encoding="utf-8")

def generer_texte_commentaire(item, titre_article, art_info, parent_texte=None):
    """Génère le texte d'un commentaire via Claude."""
    type_msg = item["type_message"]
    profil   = item["profil"]
    style    = item["style"]
    region   = item["region"]

    contexte_parent = f"\nIl répond à ce commentaire précédent : '{parent_texte[:150]}...'" if parent_texte else ""

    prompt = f"""Tu es {profil}, habitant(e) en {region}. 
Ton style : {style}
Tu laisses un commentaire de type "{type_msg}" sur cet article : "{titre_article}"
{contexte_parent}

CONSIGNES ABSOLUES :
- Écris UNIQUEMENT le texte du commentaire, rien d'autre
- 2-4 phrases maximum, ton naturel et humain
- Parle en français naturel, pas d'anglicismes
- Mentionne ta région si c'est naturel dans le contexte
- Sois spécifique à l'article, pas générique
- Pour "question_pratique" : pose une vraie question pratique
- Pour "retour_experience" : partage une vraie expérience personnelle avec détails
- Pour "demande_prix_devis" : demande des prix pour une situation précise
- Pour "complement_information" : ajoute une info utile et spécifique
- Pour "remerciement_avec_question" : remercie puis pose une question
- Varie le niveau de langue selon le profil (ouvrier vs médecin vs retraité)
- NE PAS commencer par "Bonjour" ou "Merci pour cet article"

Écris uniquement le texte du commentaire :"""

    return appeler_claude(prompt, max_tokens=200)

def regenerer_blog_avec_commentaires(slug, comments_data, archi, articles):
    """Ajoute les commentaires en HTML statique dans la page blog."""
    blog_file = Path(f"blog/{slug}.html")
    if not blog_file.exists():
        return

    html = blog_file.read_text(encoding="utf-8")
    commentaires = comments_data.get(slug, [])

    if not commentaires:
        return

    # Générer HTML commentaires
    html_comments = '<div class="commentaires-section" id="commentaires"><h2>Commentaires</h2><div id="liste-commentaires">'
    
    for c in commentaires:
        initiale = c["auteur"][0].upper()
        html_comments += f"""
        <div class="commentaire" id="{c['id']}">
            <div class="comment-header">
                <span class="comment-avatar">{initiale}</span>
                <strong class="comment-auteur">{c['auteur']}</strong>
                <span class="comment-region">{c.get('region','')}</span>
                <span class="comment-date">{c['date']}</span>
            </div>
            <p class="comment-texte">{c['texte']}</p>"""
        
        for r in c.get("reponses", []):
            initiale_r = r["auteur"][0].upper()
            html_comments += f"""
            <div class="commentaire reponse" id="{r['id']}">
                <div class="comment-header">
                    <span class="comment-avatar">{initiale_r}</span>
                    <strong class="comment-auteur">{r['auteur']}</strong>
                    <span class="comment-region">{r.get('region','')}</span>
                    <span class="comment-date">{r['date']}</span>
                </div>
                <p class="comment-texte">{r['texte']}</p>"""
            
            for cr in r.get("reponses", []):
                initiale_cr = cr["auteur"][0].upper()
                html_comments += f"""
                <div class="commentaire contre-reponse" id="{cr['id']}">
                    <div class="comment-header">
                        <span class="comment-avatar">{initiale_cr}</span>
                        <strong class="comment-auteur">{cr['auteur']}</strong>
                        <span class="comment-region">{cr.get('region','')}</span>
                        <span class="comment-date">{cr['date']}</span>
                    </div>
                    <p class="comment-texte">{cr['texte']}</p>
                </div>"""
            
            html_comments += '</div>'
        
        html_comments += '</div>'
    
    html_comments += '</div></div>'

    # Remplacer la section commentaires
    html = re.sub(
        r'<div class="commentaires-section".*?</div>\s*</div>',
        html_comments,
        html,
        flags=re.DOTALL
    )
    blog_file.write_text(html, encoding="utf-8")
    print(f"  ✅ Commentaires mis à jour : {slug}")

# ─── PAGE BLOG ────────────────────────────────────────────
ARTICLES_PAR_PAGE_BLOG   = 30  # Nombre d'articles par page de pagination
ARTICLES_PAR_SECTION_PILIER = 6  # Nombre d'articles affichés dans chaque section pilier

def _card_article_blog(art):
    """Génère une card unique pour un article de blog (format commun)."""
    thumb = art.get("thumb", "")
    img   = img_responsive(thumb, art["titre"], role="card", loading="lazy", classe="card-image") if thumb else ""
    desc  = art.get('description', '')[:110]
    if desc and len(art.get('description', '')) > 110:
        desc = desc.rsplit(" ", 1)[0] + "…"
    return f"""
    <a href="/blog/{art['slug']}.html" class="article-card">
      {img}
      <div class="card-body">
        <span class="categorie">{art.get('categorie', 'Blog')}</span>
        <h3 class="card-titre">{art['titre']}</h3>
        <p>{desc}</p>
      </div>
    </a>"""

def _bloc_pagination(page_actuelle, nb_pages):
    """Génère le bloc de pagination avec liens Précédent/Suivant et numéros.
    page_actuelle commence à 1. nb_pages est le total des pages."""
    if nb_pages <= 1:
        return ""

    def url_page(n):
        """URL d'une page. Page 1 = /blog.html, sinon /blog/page-N.html"""
        return "/blog.html" if n == 1 else f"/blog/page-{n}.html"

    html = '<nav class="pagination" aria-label="Pagination des articles du blog">'
    # Précédent
    if page_actuelle > 1:
        html += f'<a href="{url_page(page_actuelle - 1)}" class="pagination-nav" rel="prev">‹ Précédent</a>'
    else:
        html += '<span class="pagination-nav pagination-disabled">‹ Précédent</span>'

    # Numéros de pages (on affiche page actuelle ± 2, avec … si besoin)
    html += '<div class="pagination-numbers">'
    for n in range(1, nb_pages + 1):
        if n == page_actuelle:
            html += f'<span class="pagination-current" aria-current="page">{n}</span>'
        elif n == 1 or n == nb_pages or abs(n - page_actuelle) <= 2:
            html += f'<a href="{url_page(n)}" class="pagination-link">{n}</a>'
        elif abs(n - page_actuelle) == 3:
            html += '<span class="pagination-ellipsis">…</span>'
    html += '</div>'

    # Suivant
    if page_actuelle < nb_pages:
        html += f'<a href="{url_page(page_actuelle + 1)}" class="pagination-nav" rel="next">Suivant ›</a>'
    else:
        html += '<span class="pagination-nav pagination-disabled">Suivant ›</span>'

    html += '</nav>'
    return html

def _css_blog_index():
    """CSS spécifique aux pages d'index du blog (blog.html + pagination)."""
    return '''
  <style>
    .blog-hero{max-width:1100px;margin:30px auto 0;padding:0 20px;text-align:center;}
    .blog-hero h1{font-family:Georgia,serif;color:var(--vert,#2d5a3d);
      font-size:2.2rem;margin:0 0 10px;font-weight:500;}
    .blog-hero-intro{color:#666;font-size:1.05rem;max-width:680px;
      margin:0 auto 10px;line-height:1.6;}

    .blog-section{max-width:1200px;margin:50px auto;padding:0 20px;}
    .blog-section h2{font-family:Georgia,serif;color:var(--vert,#2d5a3d);
      font-size:1.7rem;margin:0 0 6px;font-weight:500;}
    .blog-section h2::after{content:"";display:block;width:60px;height:2px;
      background:#c5a572;margin:12px 0 0;}
    .blog-section-intro{color:#666;font-size:.98rem;margin:8px 0 24px;
      line-height:1.55;}
    .blog-section-all{display:inline-block;margin-top:18px;color:#2d5a3d;
      font-weight:600;text-decoration:none;border-bottom:1px solid #c5a572;
      padding-bottom:2px;}
    .blog-section-all:hover{color:#c5a572;}

    .articles-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
      gap:22px;}
    .article-card{background:#fff;border-radius:10px;overflow:hidden;text-decoration:none;
      color:inherit;border:1px solid #e8e8e0;transition:transform .2s,box-shadow .2s;
      display:flex;flex-direction:column;}
    .article-card:hover{transform:translateY(-3px);box-shadow:0 8px 24px rgba(45,90,61,.12);}
    .article-card .card-image{width:100%;height:170px;object-fit:cover;display:block;
      background:#f0ede5;}
    .article-card .card-body{padding:16px;flex:1;display:flex;flex-direction:column;}
    .article-card .categorie{display:inline-block;background:#fafaf7;color:#2d5a3d;
      padding:3px 10px;border-radius:4px;font-size:.78rem;font-weight:500;
      letter-spacing:.5px;text-transform:uppercase;margin-bottom:10px;align-self:flex-start;}
    .article-card .card-titre{font-family:Georgia,serif;color:#2d5a3d;font-size:1.08rem;
      font-weight:500;margin:0 0 8px;line-height:1.35;}
    .article-card p{color:#555;font-size:.9rem;line-height:1.5;margin:0;}

    .blog-all-section{max-width:1200px;margin:60px auto 30px;padding:40px 20px 0;
      border-top:1px solid #e8e8e0;}
    .blog-all-section h2{font-family:Georgia,serif;color:var(--vert,#2d5a3d);
      font-size:1.7rem;text-align:center;margin:0 0 30px;font-weight:500;}

    /* Pagination */
    .pagination{display:flex;align-items:center;justify-content:center;gap:14px;
      margin:40px auto 60px;flex-wrap:wrap;max-width:1100px;padding:0 20px;}
    .pagination-nav{display:inline-block;padding:10px 18px;background:#2d5a3d;
      color:#fff;text-decoration:none;border-radius:6px;font-weight:500;
      transition:background .2s;}
    .pagination-nav:hover{background:#234730;}
    .pagination-disabled{background:#e8e8e0;color:#999;cursor:not-allowed;pointer-events:none;}
    .pagination-numbers{display:flex;gap:6px;align-items:center;}
    .pagination-link{display:inline-block;padding:8px 14px;color:#2d5a3d;
      text-decoration:none;border-radius:6px;border:1px solid #e8e8e0;
      min-width:40px;text-align:center;font-weight:500;transition:all .2s;}
    .pagination-link:hover{background:#fafaf7;border-color:#c5a572;}
    .pagination-current{display:inline-block;padding:8px 14px;background:#c5a572;
      color:#fff;border-radius:6px;min-width:40px;text-align:center;font-weight:500;}
    .pagination-ellipsis{color:#999;padding:0 4px;}
  </style>'''

def _rendre_page_blog_pagination(archi, articles, page_num, nb_pages):
    """Génère une page de pagination simple (page-2.html, page-3.html, etc.).
    Affiche juste une grille d'articles triés + pagination."""
    debut = (page_num - 1) * ARTICLES_PAR_PAGE_BLOG
    fin   = debut + ARTICLES_PAR_PAGE_BLOG
    articles_page = articles[debut:fin]

    cards = "".join(_card_article_blog(a) for a in articles_page)

    # URL canonique et titre
    url_page = f"{SITE_URL}/blog/page-{page_num}.html"
    titre_page = f"Blog Pergola — Page {page_num} | {SITE_NOM}"
    desc_page = f"Articles {debut+1} à {min(fin, len(articles))} sur {len(articles)} — Tous nos conseils et guides pergolas en France."

    # Image OG
    og_image = "/images/home/slider-1.webp"
    if articles_page and articles_page[0].get("thumb"):
        og_image = articles_page[0]["thumb"]

    # Balises rel prev/next pour signal SEO
    rel_links = ""
    if page_num > 1:
        prev_url = f"{SITE_URL}/blog.html" if page_num == 2 else f"{SITE_URL}/blog/page-{page_num-1}.html"
        rel_links += f'<link rel="prev" href="{prev_url}">\n  '
    if page_num < nb_pages:
        rel_links += f'<link rel="next" href="{SITE_URL}/blog/page-{page_num+1}.html">\n  '

    pagination_html = _bloc_pagination(page_num, nb_pages)

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{titre_page}</title>
  <meta name="description" content="{desc_page}">
  {meta_commune()}
  {meta_sociales(titre=titre_page, description=desc_page, image_url=og_image,
                 url_page=url_page, type_og="website")}
  <link rel="canonical" href="{url_page}">
  {rel_links}{lien_css()}
{_css_blog_index()}
</head>
<body>
  {construire_header(archi, "blog")}
  <main class="container">
    <section class="blog-hero">
      <nav class="fil-ariane"><a href="/">Accueil</a> › <a href="/blog.html">Blog</a> › <span>Page {page_num}</span></nav>
      <h1>Blog Pergola — Page {page_num}</h1>
      <p class="blog-hero-intro">Articles {debut+1} à {min(fin, len(articles))} sur un total de {len(articles)} publications.</p>
    </section>
    <section class="blog-all-section" style="margin-top:30px;border-top:none;padding-top:0;">
      <div class="articles-grid">{cards}</div>
      {pagination_html}
    </section>
  </main>
  {construire_footer("blog")}
  {lien_js()}
  {banner_cookies()}
</body></html>"""

    # Créer dossier /blog/ si besoin et écrire la page
    Path("blog").mkdir(exist_ok=True)
    Path(f"blog/page-{page_num}.html").write_text(html, encoding="utf-8")

def generer_page_blog(archi, articles):
    """Génère la page d'accueil du blog /blog.html avec :
    - Hero + intro
    - Une section H2 par pilier (6 derniers articles du pilier)
    - Une section "Tous les derniers articles" avec pagination

    Génère aussi les pages de pagination /blog/page-2.html, /blog/page-3.html, etc.
    """
    # Tri chronologique décroissant (articles les plus récents d'abord)
    articles_tries = sorted(articles, key=lambda a: a.get("date", "1970-01-01"), reverse=True)

    # ─── Sections par pilier ───
    sections_piliers_html = ""
    for pilier in archi["piliers"]:
        arts_pilier = [a for a in articles_tries if a.get("pilier_id") == pilier["id"]][:ARTICLES_PAR_SECTION_PILIER]
        if not arts_pilier:
            # On affiche quand même la section si pas d'articles, avec un message placeholder
            continue

        cards_pilier = "".join(_card_article_blog(a) for a in arts_pilier)
        titre_pilier_bas = pilier['titre'].lower()
        sections_piliers_html += f'''
    <section class="blog-section">
      <h2>{pilier['titre'].capitalize()}</h2>
      <p class="blog-section-intro">Les derniers conseils et guides pratiques sur {titre_pilier_bas}.</p>
      <div class="articles-grid">{cards_pilier}</div>
      <a href="/{pilier['slug']}.html" class="blog-section-all">Voir le guide complet sur {titre_pilier_bas} →</a>
    </section>'''

    # ─── Section "Tous les derniers articles" (page 1) ───
    # On affiche les 30 derniers articles + pagination si plus
    nb_total = len(articles_tries)
    nb_pages = max(1, (nb_total + ARTICLES_PAR_PAGE_BLOG - 1) // ARTICLES_PAR_PAGE_BLOG)

    articles_page_1 = articles_tries[:ARTICLES_PAR_PAGE_BLOG]
    cards_page_1 = "".join(_card_article_blog(a) for a in articles_page_1)

    section_tous_html = ""
    if articles_page_1:
        section_tous_html = f'''
    <section class="blog-all-section">
      <h2>Tous les derniers articles</h2>
      <div class="articles-grid">{cards_page_1}</div>
      {_bloc_pagination(1, nb_pages)}
    </section>'''

    # ─── Image OG ───
    og_image = "/images/home/slider-1.webp"
    if articles_tries and articles_tries[0].get("thumb"):
        og_image = articles_tries[0]["thumb"]

    # ─── Balise rel="next" si pagination ───
    rel_next = f'<link rel="next" href="{SITE_URL}/blog/page-2.html">' if nb_pages > 1 else ''

    # ─── HTML complet de /blog.html ───
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Blog Pergola | {SITE_NOM}</title>
  <meta name="description" content="Tous nos articles et conseils sur les pergolas en France : prix, installation, entretien, réglementation, comparatifs.">
  {meta_commune()}
  {meta_sociales(
    titre=f"Blog Pergola — {SITE_NOM}",
    description="Tous nos articles et conseils sur les pergolas en France : prix, installation, entretien, réglementation.",
    image_url=og_image,
    url_page=f"{SITE_URL}/blog.html",
    type_og="website"
  )}
  <link rel="canonical" href="{SITE_URL}/blog.html">
  {rel_next}
  {lien_css()}
{_css_blog_index()}
</head>
<body>
  {construire_header(archi, "blog")}
  <main class="container">
    <section class="blog-hero">
      <h1>Blog &amp; Conseils Pergola</h1>
      <p class="blog-hero-intro">Retrouvez tous nos guides, comparatifs et conseils pratiques sur les pergolas en France — classés par thématique.</p>
    </section>

    {sections_piliers_html}

    {section_tous_html}
  </main>
  {construire_footer("blog")}
  {lien_js()}
  {banner_cookies()}
</body></html>"""
    Path("blog.html").write_text(html, encoding="utf-8")

    # ─── Génération des pages de pagination (page-2, page-3, etc.) ───
    if nb_pages > 1:
        for page_num in range(2, nb_pages + 1):
            _rendre_page_blog_pagination(archi, articles_tries, page_num, nb_pages)
        print(f"  ✅ /blog.html + {nb_pages - 1} page(s) de pagination (blog/page-2.html à blog/page-{nb_pages}.html)")
    else:
        print(f"  ✅ /blog.html ({nb_total} articles)")

# ─── SITEMAP ──────────────────────────────────────────────
def generer_sitemap(archi, articles):
    urls = [f'<url><loc>{SITE_URL}/</loc><priority>1.0</priority><changefreq>daily</changefreq></url>']
    urls.append(f'<url><loc>{SITE_URL}/blog.html</loc><priority>0.9</priority><changefreq>daily</changefreq></url>')

    # Pages de pagination du blog (si assez d'articles pour générer des pages supplémentaires)
    nb_pages_blog = max(1, (len(articles) + ARTICLES_PAR_PAGE_BLOG - 1) // ARTICLES_PAR_PAGE_BLOG)
    for n in range(2, nb_pages_blog + 1):
        urls.append(f'<url><loc>{SITE_URL}/blog/page-{n}.html</loc><priority>0.7</priority><changefreq>weekly</changefreq></url>')

    for p in archi["piliers"]:
        # URL pilier : /{slug}.html
        urls.append(f'<url><loc>{SITE_URL}/{p["slug"]}.html</loc><priority>0.9</priority><changefreq>monthly</changefreq></url>')
        for s in p["secondaires"]:
            # URL secondaire : /{pilier_id}/{slug}.html
            urls.append(f'<url><loc>{SITE_URL}/{p["id"]}/{s["slug"]}.html</loc><priority>0.8</priority><changefreq>monthly</changefreq></url>')
    for art in articles:
        urls.append(f'<url><loc>{SITE_URL}/blog/{art["slug"]}.html</loc><lastmod>{art["date"]}</lastmod><priority>0.6</priority><changefreq>yearly</changefreq></url>')

    Path("sitemap.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{''.join(urls)}
</urlset>""", encoding="utf-8")
    print("✅ sitemap.xml")

def ping_google_sitemap():
    """Notifie Google du nouveau sitemap."""
    try:
        url = f"https://www.google.com/ping?sitemap={urllib.parse.quote(f'{SITE_URL}/sitemap.xml')}"
        urllib.request.urlopen(url, timeout=5)
        print("✅ Google pingué")
    except Exception as e:
        print(f"  ⚠️ Ping Google: {e}")

# ─── ROBOTS.TXT ───────────────────────────────────────────
# ─── FLUX RSS (pour Google Discover "Suivre") ─────────────
def generer_feed_rss(articles):
    """Génère /feed.xml (RSS 2.0) avec les 20 derniers articles.
    Critique pour Google Discover : permet aux utilisateurs de "suivre" le site
    via la fonction Follow disponible sur Android/Chrome."""
    from xml.sax.saxutils import escape as xml_escape

    articles_tries = sorted(
        articles,
        key=lambda a: a.get("date", "1970-01-01"),
        reverse=True
    )[:20]

    # Format date RFC-822 pour le RSS
    def date_rfc822(iso_date):
        try:
            dt = datetime.strptime(iso_date, "%Y-%m-%d")
            return dt.strftime("%a, %d %b %Y 08:00:00 +0100")
        except Exception:
            return datetime.now().strftime("%a, %d %b %Y 08:00:00 +0100")

    items = ""
    for art in articles_tries:
        url   = f"{SITE_URL}/blog/{art['slug']}.html"
        titre = xml_escape(art.get("titre", ""))
        desc  = xml_escape(art.get("description", ""))
        date_rfc = date_rfc822(art.get("date", ""))
        categorie = xml_escape(art.get("categorie", "Blog"))
        items += f"""
    <item>
      <title>{titre}</title>
      <link>{url}</link>
      <guid isPermaLink="true">{url}</guid>
      <description>{desc}</description>
      <pubDate>{date_rfc}</pubDate>
      <category>{categorie}</category>
      <author>contact@eoliz.fr ({xml_escape(AUTEUR_NOM)})</author>
    </item>"""

    build_date = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0100")
    site_titre = xml_escape(f"{SITE_NOM} — {SITE_DESCRIPTION_COURTE}")
    site_desc  = xml_escape(SITE_DESCRIPTION_COURTE)

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{site_titre}</title>
    <link>{SITE_URL}/</link>
    <description>{site_desc}</description>
    <language>fr-FR</language>
    <lastBuildDate>{build_date}</lastBuildDate>
    <atom:link href="{SITE_URL}/feed.xml" rel="self" type="application/rss+xml"/>{items}
  </channel>
</rss>
"""
    Path("feed.xml").write_text(rss, encoding="utf-8")
    print(f"✅ feed.xml ({len(articles_tries)} articles)")

def generer_robots_txt():
    """Génère le fichier robots.txt à la racine."""
    contenu = f"""User-agent: *
Allow: /

# Sitemap XML
Sitemap: {SITE_URL}/sitemap.xml

# Interdire l'indexation des pages d'admin éventuelles
Disallow: /admin/
Disallow: /.github/
"""
    Path("robots.txt").write_text(contenu, encoding="utf-8")
    print("✅ robots.txt")

# ─── PAGES LÉGALES ────────────────────────────────────────
def _page_legale_template(archi, titre, contenu_html):
    """Template générique pour les pages légales (mentions, confidentialité, cookies)."""
    slug = slugify(titre) + ".html"
    page_url = f"{SITE_URL}/{slug}"
    breadcrumb = schema_breadcrumb([
        {"name": "Accueil", "url": f"{SITE_URL}/"},
        {"name": titre, "url": page_url}
    ])
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{titre} | {SITE_NOM}</title>
  <meta name="description" content="{titre} du site {SITE_NOM}.">
  {meta_commune()}
  {meta_sociales(
    titre=f"{titre} | {SITE_NOM}",
    description=f"{titre} du site {SITE_NOM}.",
    image_url="/images/home/slider-1.webp",
    url_page=page_url,
    type_og="website"
  )}
  <link rel="canonical" href="{page_url}">
  {lien_css()}
  <style>
    .page-legale{{max-width:820px;margin:40px auto;padding:0 20px;line-height:1.75;color:#222;}}
    .page-legale h1{{font-family:Georgia,serif;color:var(--vert,#2d5a3d);font-size:2rem;margin:0 0 24px;}}
    .page-legale h2{{font-family:Georgia,serif;color:var(--vert,#2d5a3d);font-size:1.3rem;margin:32px 0 14px;}}
    .page-legale p{{margin:0 0 14px;}}
    .page-legale ul{{margin:0 0 16px;padding-left:22px;}}
    .page-legale li{{margin-bottom:6px;}}
    .page-legale a{{color:var(--vert,#2d5a3d);}}
  </style>
  <script type="application/ld+json">{breadcrumb}</script>
</head>
<body>
  {construire_header(archi, "racine")}
  <main class="page-legale">
    <nav class="fil-ariane"><a href="/">Accueil</a> › <span>{titre}</span></nav>
    <h1>{titre}</h1>
    {contenu_html}
    <p style="margin-top:40px;color:#888;font-size:.85rem;">Dernière mise à jour : {datetime.now().strftime('%d/%m/%Y')}</p>
  </main>
  {construire_footer("racine")}
  {lien_js()}
  {banner_cookies()}
</body></html>"""
    Path(slug).write_text(html, encoding="utf-8")
    print(f"✅ {slug}")

def generer_pages_legales(archi):
    """Génère mentions-legales, politique-confidentialite, cookies."""
    # ─── Mentions légales ───
    _page_legale_template(archi, "Mentions légales", """
    <h2>Éditeur du site</h2>
    <p>Le site <strong>""" + SITE_NOM + """</strong> (""" + SITE_URL + """) est édité par :</p>
    <ul>
      <li><strong>EOLIZ</strong></li>
      <li>Contact : <a href="mailto:contact@eoliz.fr">contact@eoliz.fr</a></li>
    </ul>
    <h2>Directeur de la publication</h2>
    <p>Ludovic Levé, représentant légal d'EOLIZ.</p>
    <h2>Hébergement</h2>
    <p>Le site est hébergé par GitHub Pages — GitHub Inc., 88 Colin P Kelly Jr St, San Francisco, CA 94107, USA.</p>
    <h2>Propriété intellectuelle</h2>
    <p>L'ensemble des contenus présents sur ce site (textes, images, structure, charte graphique) est la propriété exclusive d'EOLIZ, sauf mention contraire. Toute reproduction, représentation ou diffusion, totale ou partielle, sans autorisation écrite préalable est strictement interdite.</p>
    <h2>Crédits images</h2>
    <p>Les images illustrant ce site sont soit générées par intelligence artificielle (FLUX via Replicate), soit issues de la banque d'images Unsplash avec mention des auteurs lorsque requis.</p>
    <h2>Limitation de responsabilité</h2>
    <p>Les informations fournies sur ce site sont données à titre indicatif et ne sauraient engager la responsabilité de l'éditeur. Les prix, normes et réglementations évoluent : merci de vérifier auprès de sources officielles avant toute décision.</p>
    """)

    # ─── Politique de confidentialité ───
    fallback_ga = "<p>Aucun outil de mesure d'audience n'est actuellement actif sur ce site.</p>"
    fallback_ads = "<p>Aucune publicité n'est actuellement diffusée sur ce site.</p>"

    ga_mention = ""
    if GA4_ID:
        ga_mention = "<p>Ce site utilise <strong>Google Analytics 4</strong> pour mesurer l'audience de manière anonymisée. Aucune donnée personnelle identifiable n'est collectée. Les adresses IP sont anonymisées. Vous pouvez refuser ce traceur via la banner de consentement.</p>"
    else:
        ga_mention = fallback_ga

    adsense_mention = ""
    if ADSENSE_ACTIF:
        adsense_mention = "<p>Ce site affiche des annonces publicitaires via <strong>Google AdSense</strong>. Ces annonces peuvent être personnalisées en fonction de vos centres d'intérêt si vous y avez consenti. Vous pouvez désactiver la personnalisation via la banner cookies.</p>"
    else:
        adsense_mention = fallback_ads

    _page_legale_template(archi, "Politique de confidentialité", f"""
    <h2>Responsable du traitement</h2>
    <p>EOLIZ, éditeur de <strong>{SITE_NOM}</strong>, est responsable du traitement de vos données personnelles sur ce site. Contact : <a href="mailto:contact@eoliz.fr">contact@eoliz.fr</a>.</p>
    <h2>Données collectées</h2>
    <p>Ce site ne demande pas la création de compte utilisateur. Les seules données collectées le sont de manière automatique à des fins statistiques (si vous l'acceptez) :</p>
    <ul>
      <li>Adresse IP anonymisée</li>
      <li>Pages visitées et durée</li>
      <li>Type de navigateur et appareil</li>
      <li>Source de trafic (référent)</li>
    </ul>
    <h2>Outils de mesure d'audience</h2>
    {ga_mention}
    <h2>Publicité</h2>
    {adsense_mention}
    <h2>Durée de conservation</h2>
    <p>Les données statistiques sont conservées 13 mois maximum, conformément aux recommandations de la CNIL.</p>
    <h2>Vos droits</h2>
    <p>Conformément au RGPD, vous disposez d'un droit d'accès, de rectification, d'effacement, de limitation du traitement, de portabilité et d'opposition. Pour exercer ces droits, contactez-nous à <a href="mailto:contact@eoliz.fr">contact@eoliz.fr</a>.</p>
    <p>Vous pouvez également introduire une réclamation auprès de la CNIL : <a href="https://www.cnil.fr" target="_blank" rel="noopener">www.cnil.fr</a>.</p>
    <h2>Cookies</h2>
    <p>Consultez notre <a href="/cookies.html">page dédiée aux cookies</a> pour plus de détails.</p>
    """)

    # ─── Page cookies ───
    _page_legale_template(archi, "Cookies", """
    <h2>Qu'est-ce qu'un cookie ?</h2>
    <p>Un cookie est un petit fichier déposé sur votre navigateur lors de la visite d'un site. Il permet notamment de retenir vos préférences et de mesurer la fréquentation du site.</p>
    <h2>Cookies utilisés sur ce site</h2>
    <h3 style="font-size:1.1rem;color:#2d5a3d;margin:20px 0 10px;">Cookies essentiels (toujours actifs)</h3>
    <ul>
      <li><strong>pg_consent</strong> : mémorise vos choix concernant les cookies (durée : 13 mois, stocké dans votre navigateur).</li>
    </ul>
    <h3 style="font-size:1.1rem;color:#2d5a3d;margin:20px 0 10px;">Cookies de mesure d'audience (optionnels)</h3>
    <p>Si vous avez accepté la mesure d'audience, les cookies suivants peuvent être déposés :</p>
    <ul>
      <li><strong>_ga, _ga_*</strong> : Google Analytics 4, pour mesurer la fréquentation (durée : 13 mois).</li>
    </ul>
    <h3 style="font-size:1.1rem;color:#2d5a3d;margin:20px 0 10px;">Cookies publicitaires (optionnels)</h3>
    <p>Si vous avez accepté la publicité personnalisée, des cookies Google AdSense peuvent être déposés afin d'afficher des annonces adaptées à vos centres d'intérêt.</p>
    <h2>Modifier vos préférences</h2>
    <p>Vous pouvez à tout moment modifier vos choix en cliquant sur le bouton ci-dessous :</p>
    <p><button onclick="window.pgConsent && window.pgConsent.reset();" style="padding:10px 18px;background:#2d5a3d;color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:600;">Modifier mes préférences cookies</button></p>
    """)

# ─── MODE FIX : régénérer tout le HTML sans appeler Claude/Replicate ───
def mode_fix(archi):
    """Régénère toutes les pages HTML à partir des données existantes.
    N'appelle PAS Claude ni Replicate. Utilisé pour appliquer des modifs
    de template, CSS, GA4, GSC, banner cookies... sans coût API.

    Pour que ça fonctionne, on a besoin que le contenu des pages soit stocké.
    Comme on ne stocke pas ça actuellement, le mode fix regénère uniquement :
    - index.html
    - blog.html
    - robots.txt
    - sitemap.xml
    - pages légales
    - banner cookies / GA / GSC sur toutes les pages existantes (par injection HTML)
    """
    print("🔧 Mode FIX : mise à jour des templates sans appel API")
    articles = charger_articles()

    # Régénération des pages "template-only" (pas de contenu Claude)
    generer_accueil(archi, articles, regenerer_images=False)
    generer_page_blog(archi, articles)
    generer_sitemap(archi, articles)
    generer_robots_txt()
    generer_pages_legales(archi)
    generer_page_a_propos(archi)           # Page auteur (E-E-A-T, critique Discover)
    generer_feed_rss(articles)             # Flux RSS (pour "Follow" dans Discover)

    # Injection GA/GSC/banner sur les pages déjà générées (piliers + secondaires + articles blog)
    print("  🔄 Mise à jour des balises sur pages existantes...")
    nb_patched = 0
    for html_file in list(Path(".").glob("*.html")) + list(Path("blog").glob("*.html")):
        for pilier in archi["piliers"]:
            pass  # les html piliers sont à la racine, déjà couverts
    # Glob toutes les pages HTML existantes dans les dossiers des piliers
    for pilier in archi["piliers"]:
        for f in Path(pilier["id"]).glob("*.html"):
            if _injecter_tags_seo(f):
                nb_patched += 1
    for f in Path("blog").glob("*.html"):
        if _injecter_tags_seo(f):
            nb_patched += 1
    for f in Path(".").glob("*.html"):
        if _injecter_tags_seo(f):
            nb_patched += 1

    print(f"  ✅ {nb_patched} pages patchées")
    print("🎉 Mode FIX terminé — coût : 0 €")

def _injecter_tags_seo(html_path):
    """Met à jour une page HTML existante : remplace les balises GA/GSC/cookies
    ET normalise les URLs (canonical, JSON-LD, OG) vers la SITE_URL actuelle.
    Retourne True si la page a été modifiée."""
    try:
        html = html_path.read_text(encoding="utf-8")
        original = html

        # ─── 0. Normalisation des URLs : variante with/without www ────
        # Si SITE_URL n'a pas "www", on remplace "www.<domaine>" par "<domaine>"
        # Si SITE_URL a "www", on fait l'inverse.
        # Cela corrige canonical, JSON-LD (breadcrumb, Article), OpenGraph, etc.
        try:
            from urllib.parse import urlparse
            parsed = urlparse(SITE_URL)
            domaine = parsed.netloc  # ex: "pergola-guide.fr" ou "www.pergola-guide.fr"
            if domaine.startswith("www."):
                domaine_sans_www = domaine[4:]
                # SITE_URL contient www → remplacer les versions sans www par celles avec www
                html = html.replace(f"https://{domaine_sans_www}/", f"https://{domaine}/")
                html = html.replace(f'"https://{domaine_sans_www}"', f'"https://{domaine}"')
            else:
                domaine_avec_www = f"www.{domaine}"
                # SITE_URL sans www → remplacer les versions avec www par celles sans www
                html = html.replace(f"https://{domaine_avec_www}/", f"https://{domaine}/")
                html = html.replace(f'"https://{domaine_avec_www}"', f'"https://{domaine}"')
        except Exception as e:
            print(f"  ⚠️ Normalisation URL : {e}")

        # 1. Remplacer la balise GSC
        new_gsc = balise_gsc()
        html = re.sub(
            r'<meta name="google-site-verification"[^>]*>|<!-- GSC : non configuré -->',
            new_gsc,
            html,
            count=1
        )

        # 2. Remplacer le bloc GA4 (on cherche entre les deux commentaires repères)
        # Le script GA4 commence par <!-- Google Analytics 4 ou par le commentaire de désactivation
        new_ga = script_ga4_head()
        # Remplacement du bloc GA si présent
        html = re.sub(
            r'<!-- Google Analytics 4[^<]*-->.*?<script async src="https://www\.googletagmanager\.com/gtag/js\?id=[^"]*"></script>',
            new_ga,
            html,
            count=1,
            flags=re.DOTALL
        )
        html = re.sub(r'<!-- GA4 : non configuré -->', new_ga, html, count=1)

        # 3. Remplacer le script AdSense
        new_adsense = script_adsense_head()
        html = re.sub(
            r'<script async src="https://pagead2\.googlesyndication\.com/[^"]*"[^>]*></script>',
            new_adsense,
            html,
            count=1
        )
        html = re.sub(r'<!-- AdSense : inactif pour l\'instant -->', new_adsense, html, count=1)

        # 4. Remplacer le banner cookies (bloc complet entre les commentaires repères)
        # Le banner est injecté à la fin, juste avant </body>
        # On retire l'ancien bloc s'il existe et on réinjecte
        new_banner = banner_cookies()
        # Détection de l'ancien bloc via le commentaire repère
        pattern_banner = r'<!-- Banner cookies RGPD \(CNIL-compliant\) -->.*?</script>\s*(?=</body>)'
        if re.search(pattern_banner, html, re.DOTALL):
            html = re.sub(pattern_banner, new_banner.strip() + '\n', html, count=1, flags=re.DOTALL)
        elif '</body>' in html and 'pg-cookie-banner' not in html:
            # Pas de banner du tout : on l'injecte avant </body>
            html = html.replace('</body>', new_banner + '\n</body>', 1)

        # 5. Remplacer l'ancien HTML du logo par le nouveau (Variante B style magazine)
        # Ancien format : <a href="/" class="logo">🏡 Guide Pergola</a>
        # Nouveau format : <a href="/" class="logo"><span class="logo-pergola">...</span>...</a>
        # On cherche la balise <a class="logo"> et on remplace son contenu, quel qu'il soit.
        html = re.sub(
            r'(<a[^>]*class="logo"[^>]*>)(.*?)(</a>)',
            lambda m: m.group(1) + SITE_LOGO + m.group(3),
            html,
            flags=re.DOTALL
        )

        if html != original:
            html_path.write_text(html, encoding="utf-8")
            return True
        return False
    except Exception as e:
        print(f"  ⚠️ Erreur patch {html_path} : {e}")
        return False

# ─── MAIN ─────────────────────────────────────────────────
def main():
    import sys
    archi           = charger_architecture()
    keywords        = charger_keywords()
    comments_config = charger_comments_config()
    mode = sys.argv[1] if len(sys.argv) > 1 else "blog"

    if mode == "full":
        print("🚀 Construction complète du site...")
        Path("blog").mkdir(exist_ok=True)
        for pilier in archi["piliers"]:
            Path(pilier["id"]).mkdir(exist_ok=True)

        articles = charger_articles()
        # Home en premier pour générer les 3 images du slider (si pas déjà cachées)
        generer_accueil(archi, articles, regenerer_images=True)

        for pilier in archi["piliers"]:
            generer_page_pilier(pilier, archi, keywords, articles)
            for secondaire in pilier["secondaires"]:
                generer_page_secondaire(secondaire, pilier, archi, keywords, articles)

        # Génération des premiers articles pour peupler la section "Derniers articles"
        # (uniquement si on n'a pas encore d'articles en base)
        if len(articles) == 0:
            print("\n📰 Génération des 5 premiers articles pour peupler le blog...")
            for i in range(5):
                try:
                    generer_article_blog(archi, keywords, comments_config)
                    articles = charger_articles()  # on recharge à chaque itération
                except Exception as e:
                    print(f"  ⚠️ Erreur article {i+1} : {e}")

        # Pages annexes & SEO
        generer_page_blog(archi, articles)
        generer_sitemap(archi, articles)
        generer_robots_txt()
        generer_pages_legales(archi)
        generer_page_a_propos(archi)           # Page auteur (E-E-A-T, critique Discover)
        generer_feed_rss(articles)             # Flux RSS (pour "Follow" dans Discover)

        # Régénérer la home une dernière fois pour inclure les 5 articles dans "Derniers articles"
        generer_accueil(archi, articles, regenerer_images=False)

        print("🎉 Site complet généré !")

    elif mode == "blog":
        print("📝 Génération article quotidien...")
        Path("blog").mkdir(exist_ok=True)
        generer_article_blog(archi, keywords, comments_config)
        print("🎉 Article publié !")

    elif mode == "comments":
        print("💬 Génération commentaires du jour...")
        generer_commentaires_du_jour(archi)
        print("🎉 Commentaires mis à jour !")

    elif mode == "fix":
        # Régénère templates / GA / GSC / cookies SANS appeler Claude ni Replicate
        # Parfait pour appliquer des changements de config après coup
        mode_fix(archi)

    elif mode == "optimize-images":
        # Génère les variantes responsive (400/800/1200) pour toutes les images
        # existantes SANS appeler Replicate (utilise Pillow en local).
        # À lancer après avoir ajouté le support responsive pour optimiser
        # les images déjà générées.
        print("🖼️  Mode OPTIMIZE-IMAGES : génération des variantes responsive")
        nb_images, nb_variantes = optimiser_toutes_images()
        print(f"\n🎉 {nb_images} images sources traitées")
        print(f"   {nb_variantes} variantes créées (400/800/1200)")
        print("\n➡️  Lance maintenant 'python build_site.py fix' pour mettre à jour le HTML.")

    elif mode == "reset-images":
        # Supprime toutes les images des piliers, secondaires et home
        # pour forcer leur régénération au prochain full (avec prompts améliorés).
        # PRÉSERVE /images/blog/ pour ne pas casser les articles existants.
        print("🗑️  Mode RESET-IMAGES : suppression des images piliers/secondaires/home")
        import shutil
        total = 0
        for dossier in ["images/home", "images/piliers", "images/secondaires"]:
            p = Path(dossier)
            if p.exists():
                for f in p.glob("*.webp"):
                    f.unlink()
                    total += 1
                print(f"  ✅ {dossier} nettoyé")
            else:
                print(f"  ⊘ {dossier} n'existe pas (ignoré)")
        print(f"\n🎉 {total} images supprimées.")
        print("   Dossier images/blog/ préservé (articles existants intacts).")
        print("\n➡️  Lance maintenant le workflow en mode 'full' pour régénérer.")
        print("   Coût estimé : ~1,04 € (88 images) — durée : ~30-45 min")

    else:
        print(f"❌ Mode inconnu : {mode}")
        print("   Modes disponibles : full, blog, comments, fix, optimize-images, reset-images")

if __name__ == "__main__":
    main()
