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
"""

import os, json, re, random, time, urllib.request, urllib.parse
import anthropic
from datetime import datetime
from pathlib import Path

# ─── CONFIG ───────────────────────────────────────────────
SITE_URL = "https://www.pergola-guide.fr"
SITE_NOM  = "Pergola Guide"
SITE_LOGO = "🏡 Guide Pergola"

# ─── CONFIG ADSENSE ───────────────────────────────────────
# Pour activer AdSense le moment venu :
# 1. Passer ADSENSE_ACTIF = True
# 2. Remplacer ADSENSE_CLIENT par ton vrai ID (ca-pub-XXXXXXXXXXXXXXXX)
# 3. Remplacer chaque ADSENSE_SLOT_xxx par tes vrais IDs de blocs AdSense
# 4. Relancer le workflow GitHub Actions en mode "full"
ADSENSE_ACTIF        = False
ADSENSE_CLIENT       = "ca-pub-XXXXXXXXXXXXXXXX"
ADSENSE_SLOT_HAUT    = "1111111111"   # Bloc horizontal haut (responsive)
ADSENSE_SLOT_MILIEU  = "2222222222"   # Bloc in-article (milieu contenu)
ADSENSE_SLOT_BAS     = "3333333333"   # Bloc horizontal bas (avant commentaires)
ADSENSE_SLOT_SIDEBAR = "4444444444"   # Bloc sidebar (300x250)

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
        f"Photorealistic {prompt_sujet}, beautiful French garden terrace, "
        f"sunny natural light, architectural photography, wide angle, "
        f"high quality, sharp details, no people, 16:9"
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

def get_image(sujet, modele="schnell"):
    """Essaie Replicate, fallback Unsplash."""
    img = generer_image_replicate(sujet, modele)
    if img:
        print(f"  🎨 Image FLUX générée")
        return img
    print(f"  📷 Fallback Unsplash")
    return recuperer_image_unsplash(sujet)

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
    match = re.search(f"<{balise}>(.*?)</{balise}>", texte, re.DOTALL)
    return match.group(1).strip() if match else ""

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
    data = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": h1,
        "description": meta,
        "image": image_url,
        "author": {"@type": "Organization", "name": SITE_NOM},
        "publisher": {
            "@type": "Organization",
            "name": SITE_NOM,
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

# ─── ARTICLES SIMILAIRES ──────────────────────────────────
def generer_articles_similaires(slug_actuel, pilier_id, articles, n=3):
    """Retourne HTML statique des articles similaires."""
    similaires = [
        a for a in articles
        if a.get("pilier_id") == pilier_id and a.get("slug") != slug_actuel
    ][:n]
    
    if not similaires:
        return ""
    
    html = '<div class="articles-similaires"><h2>Articles similaires</h2><div class="similaires-grid">'
    for art in similaires:
        thumb = art.get("thumb", "")
        img   = f'<img src="{thumb}" alt="{art["titre"]}" loading="lazy">' if thumb else ""
        html += f"""
        <a href="../../blog/{art['slug']}.html" class="similaire-card">
            {img}
            <div class="similaire-body">
                <span class="categorie">{art.get('categorie','Blog')}</span>
                <h3>{art['titre']}</h3>
                <p>{art.get('description','')[:80]}...</p>
            </div>
        </a>"""
    html += '</div></div>'
    return html

# ─── MAILLAGE BLOG → SECONDAIRES (statique) ───────────────
def generer_liens_blog_sur_secondaire(pilier_id, secondaire_slug, articles, n=3):
    """Articles liés affichés en HTML statique sur la page secondaire."""
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
    
    html = '<div class="connexes-grid">'
    for art in lies:
        description = art.get("description", "")[:100]
        html += f"""
        <p>Notre article sur 
        <a href="../../blog/{art['slug']}.html">{art['titre']}</a>
        — {description}...</p>"""
    html += '</div>'
    return html

# ─── HEADER / FOOTER ──────────────────────────────────────
def construire_header(archi, niveau="racine", pilier_actuel=None):
    menus = ""
    PILIERS_MENU = ["bioclimatique", "bois", "aluminium", "prix", "installation"]
    for p in [p for p in archi["piliers"] if p["id"] in PILIERS_MENU]:
        actif = "active" if pilier_actuel and p["id"] == pilier_actuel else ""
        if niveau == "racine":
            lien_pilier = f"piliers/{p['slug']}.html"
            lien_sec    = f"secondaires/{p['id']}"
        elif niveau == "pilier":
            lien_pilier = f"{p['slug']}.html"
            lien_sec    = f"../secondaires/{p['id']}"
        elif niveau == "secondaire":
            lien_pilier = f"../../piliers/{p['slug']}.html"
            lien_sec    = f"../{p['id']}"
        else:  # blog
            lien_pilier = f"../../piliers/{p['slug']}.html"
            lien_sec    = f"../../secondaires/{p['id']}"

        sous_liens = "".join(
            f'<a href="{lien_sec}/{s["slug"]}.html">{s["titre"]}</a>\n'
            for s in p["secondaires"]
        )
        menus += f"""
        <div class="menu-item {actif}">
          <a href="{lien_pilier}" class="menu-pilier">{p['titre']}</a>
          <div class="sous-menu">{sous_liens}</div>
        </div>"""

    prefix = "../../" if niveau in ["secondaire", "blog"] else ""
    return f"""<header>
  <div class="container header-inner">
    <a href="{prefix}index.html" class="logo">{SITE_LOGO}</a>
    <button class="menu-toggle" onclick="toggleMenu()">☰</button>
    <nav id="main-nav">
      <a href="{prefix}index.html">Accueil</a>
      <div class="menu-deroulant">{menus}</div>
      <a href="{prefix}blog.html">Blog</a>
    </nav>
  </div>
</header>"""

def construire_footer(niveau="racine"):
    prefix = "../../" if niveau in ["secondaire", "blog"] else ""
    return f"""<footer>
  <div class="container">
    <p>© 2025 EOLIZ — {SITE_NOM}</p>
    <p><a href="{prefix}mentions-legales.html">Mentions légales</a></p>
  </div>
</footer>"""

def meta_commune():
    """Balises meta communes à toutes les pages."""
    return '<meta name="robots" content="max-image-preview:large">\n  ' + script_adsense_head()

# ─── PAGE D'ACCUEIL ───────────────────────────────────────
def generer_accueil(archi):
    print("🏠 Génération page d'accueil...")
    cards = "".join(f"""
    <a href="piliers/{p['slug']}.html" class="pilier-card">
      <div class="pilier-card-body">
        <h2>{p['titre']}</h2><p>{p['description']}</p>
        <span class="voir-plus">Voir le guide →</span>
      </div>
    </a>""" for p in archi["piliers"])

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{SITE_NOM} — Guide complet pergolas France</title>
  <meta name="description" content="Le guide de référence sur les pergolas en France. Prix, matériaux, installation : tout pour choisir votre pergola.">
  {meta_commune()}
  <link rel="canonical" href="{SITE_URL}/index.html">
  <link rel="stylesheet" href="style.css">
</head>
<body>
  {construire_header(archi, "racine")}
  <section class="hero">
    <div class="container">
      <h1>Le guide de référence sur les pergolas en France</h1>
      <p>Prix, matériaux, installation, réglementation : tout ce qu'il faut savoir.</p>
      <a href="blog.html" class="btn-hero">Voir nos derniers articles →</a>
    </div>
  </section>
  <main class="container">
    <h2 class="section-titre">Nos guides thématiques</h2>
    <div class="piliers-grid">{cards}</div>
    <div id="derniers-articles">
      <h2 class="section-titre">Derniers articles</h2>
      <div class="articles-grid" id="grid-articles"></div>
    </div>
  </main>
  {construire_footer("racine")}
  <script src="main.js"></script>
</body></html>"""
    Path("index.html").write_text(html, encoding="utf-8")
    print("✅ index.html")

# ─── PAGE PILIER ──────────────────────────────────────────
def generer_page_pilier(pilier, archi, keywords=None, articles=None):
    print(f"📌 Pilier : {pilier['titre']}...")
    articles = articles or []
    
    # 2 images FLUX.1-dev
    img1 = get_image(f"pergola {pilier['id']} terrace garden", modele="dev")
    img2 = get_image(f"pergola {pilier['id']} installation detail", modele="dev")

    kw_block = formater_keywords_prompt(pilier['id'], keywords or {})

    prompt = f"""Tu es expert SEO et rédacteur web pergolas France.
Page pilier PARFAITEMENT optimisée SEO : {pilier['titre']}
{kw_block}
CONSIGNES :
1. Français naturel expert, public français acheteur
2. Couverture exhaustive du sujet — LA page de référence
3. Prix réalistes en euros (marché France 2024-2025)
4. Minimum 2000 mots
5. Structure : 1 H1, 5-7 H2, H3 sous chaque H2, listes <ul>, 1 tableau comparatif HTML
6. Ton expert mais accessible, orienté aide à la décision
7. Titres H2 accrocheurs intégrant des mots-clés longue traîne

Format STRICT :
<META>description 155 car. avec mot-clé principal</META>
<H1>H1 optimisé</H1>
<INTRO>2-3 phrases avec mot-clé dans la 1ère phrase</INTRO>
<CONTENU>[HTML complet h2 h3 p ul tableau]</CONTENU>
<FAQ1Q>question longue traîne</FAQ1Q><FAQ1R>réponse 2-3 phrases</FAQ1R>
<FAQ2Q>question</FAQ2Q><FAQ2R>réponse</FAQ2R>
<FAQ3Q>question</FAQ3Q><FAQ3R>réponse</FAQ3R>
<FAQ4Q>question</FAQ4Q><FAQ4R>réponse</FAQ4R>
<FAQ5Q>question</FAQ5Q><FAQ5R>réponse</FAQ5R>"""

    texte = appeler_claude(prompt, max_tokens=5000)

    h1      = extraire_balise(texte, "H1") or pilier["titre"]
    meta    = extraire_balise(texte, "META") or pilier["description"]
    intro   = extraire_balise(texte, "INTRO") or ""
    contenu = extraire_balise(texte, "CONTENU") or ""

    # FAQ
    qrs = []
    faq_html = ""
    for i in range(1, 6):
        q = extraire_balise(texte, f"FAQ{i}Q")
        r = extraire_balise(texte, f"FAQ{i}R")
        if q:
            qrs.append({"q": q, "r": r})
            faq_html += f'<div class="faq-item"><button class="faq-question">{q}</button><div class="faq-reponse">{r}</div></div>\n'

    # Liens secondaires
    liens_sec = "".join(
        f'<a href="../secondaires/{pilier["id"]}/{s["slug"]}.html" class="lien-secondaire">→ {s["titre"]}</a>\n'
        for s in pilier["secondaires"]
    )

    # Articles récents du pilier (maillage statique)
    arts_pilier = [a for a in articles if a.get("pilier_id") == pilier["id"]][:4]
    arts_html = ""
    if arts_pilier:
        arts_html = '<div class="articles-pilier"><h2>Nos derniers articles</h2><div class="articles-grid">'
        for art in arts_pilier:
            arts_html += f"""
            <a href="../blog/{art['slug']}.html" class="article-card">
                <div class="card-body">
                    <h3>{art['titre']}</h3>
                    <p>{art.get('description','')[:80]}...</p>
                </div>
            </a>"""
        arts_html += '</div></div>'

    date_modified = datetime.now().strftime("%Y-%m-%d")

    # Schemas
    breadcrumb_schema = schema_breadcrumb([
        {"name": "Accueil", "url": f"{SITE_URL}/index.html"},
        {"name": pilier["titre"], "url": f"{SITE_URL}/piliers/{pilier['slug']}.html"}
    ])
    faq_schema     = schema_faq(qrs)
    article_schema = schema_article(h1, meta, img1["url"], date_modified=date_modified)

    # HowTo pour installation
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

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{h1} | {SITE_NOM}</title>
  <meta name="description" content="{meta}">
  {meta_commune()}
  <link rel="canonical" href="{SITE_URL}/piliers/{pilier['slug']}.html">
  <link rel="stylesheet" href="../style.css">
  <script type="application/ld+json">{article_schema}</script>
  <script type="application/ld+json">{breadcrumb_schema}</script>
  {f'<script type="application/ld+json">{faq_schema}</script>' if faq_schema else ''}
  {howto_script}
</head>
<body>
  {construire_header(archi, "pilier", pilier['id'])}
  <main class="container page-pilier">
    <nav class="fil-ariane">
      <a href="../index.html">Accueil</a> › <span>{pilier['titre']}</span>
    </nav>
    <div class="pilier-hero">
      <img src="{img1['url']}" alt="{h1}" loading="lazy" width="1200">
      <div class="pilier-hero-content">
        <h1>{h1}</h1><p class="intro">{intro}</p>
      </div>
    </div>
    <div class="page-layout">
      <article class="contenu-principal">
        {bloc_adsense(ADSENSE_SLOT_HAUT, "horizontal")}
        <div class="article-body">{contenu}</div>
        <img src="{img2['url']}" alt="{h1} — détail installation" loading="lazy" width="1200" class="article-img-milieu">
        <p class="image-credit">Images générées par IA pour illustration</p>
        <div class="faq-section">
          <h2>Questions fréquentes sur {pilier['titre'].lower()}</h2>
          {faq_html}
        </div>
        {arts_html}
      </article>
      <aside class="sidebar">
        <div class="widget">
          <h3>Dans ce guide</h3>{liens_sec}
        </div>
        {bloc_adsense(ADSENSE_SLOT_SIDEBAR, "sidebar")}
      </aside>
    </div>
  </main>
  {construire_footer("pilier")}
  <script>const PILIER_ID = "{pilier['id']}";</script>
  <script src="../main.js"></script>
</body></html>"""

    Path(f"piliers/{pilier['slug']}.html").write_text(html, encoding="utf-8")
    print(f"  ✅ piliers/{pilier['slug']}.html")

# ─── PAGE SECONDAIRE ──────────────────────────────────────
def generer_page_secondaire(secondaire, pilier, archi, keywords=None, articles=None):
    print(f"  📄 Secondaire : {secondaire['titre']}...")
    articles = articles or []

    img = get_image(f"pergola {secondaire['mot_cle']}", modele="schnell")

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

    prompt = f"""Tu es expert SEO et rédacteur web pergolas France.
Page secondaire optimisée SEO : {secondaire['titre']}
Guide parent : {pilier['titre']}
{kw_block}
CONSIGNES :
1. Français naturel expert, orienté aide à la décision achat
2. Prix réalistes euros, marché France 2024-2025
3. Minimum 900 mots
4. Structure : 1 H1, 4-5 H2, H3, listes <ul>
5. Ton expert rassurant

Format STRICT :
<META>description 155 car.</META>
<H1>H1 optimisé</H1>
<INTRO>2-3 phrases, mot-clé dans la 1ère</INTRO>
<CONTENU>[HTML h2 h3 p ul]</CONTENU>
<FAQ1Q>question</FAQ1Q><FAQ1R>réponse</FAQ1R>
<FAQ2Q>question</FAQ2Q><FAQ2R>réponse</FAQ2R>
<FAQ3Q>question</FAQ3Q><FAQ3R>réponse</FAQ3R>"""

    texte   = appeler_claude(prompt, max_tokens=3000)
    h1      = extraire_balise(texte, "H1") or secondaire["titre"]
    meta    = extraire_balise(texte, "META") or secondaire["titre"]
    intro   = extraire_balise(texte, "INTRO") or ""
    contenu = extraire_balise(texte, "CONTENU") or ""

    qrs      = []
    faq_html = ""
    for i in range(1, 4):
        q = extraire_balise(texte, f"FAQ{i}Q")
        r = extraire_balise(texte, f"FAQ{i}R")
        if q:
            qrs.append({"q": q, "r": r})
            faq_html += f'<div class="faq-item"><button class="faq-question">{q}</button><div class="faq-reponse">{r}</div></div>\n'

    liens_soeurs = "".join(
        f'<a href="{s["slug"]}.html">→ {s["titre"]}</a>\n'
        for s in pilier["secondaires"] if s["slug"] != secondaire["slug"]
    )

    # Articles liés en HTML statique
    arts_connexes = generer_liens_blog_sur_secondaire(
        pilier['id'], secondaire['slug'], articles
    )

    date_modified = datetime.now().strftime("%Y-%m-%d")

    breadcrumb_schema = schema_breadcrumb([
        {"name": "Accueil", "url": f"{SITE_URL}/index.html"},
        {"name": pilier["titre"], "url": f"{SITE_URL}/piliers/{pilier['slug']}.html"},
        {"name": secondaire["titre"], "url": f"{SITE_URL}/secondaires/{pilier['id']}/{secondaire['slug']}.html"}
    ])
    faq_schema     = schema_faq(qrs)
    article_schema = schema_article(h1, meta, img["url"], date_modified=date_modified)

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{h1} | {SITE_NOM}</title>
  <meta name="description" content="{meta}">
  {meta_commune()}
  <link rel="canonical" href="{SITE_URL}/secondaires/{pilier['id']}/{secondaire['slug']}.html">
  <link rel="stylesheet" href="../../style.css">
  <script type="application/ld+json">{article_schema}</script>
  <script type="application/ld+json">{breadcrumb_schema}</script>
  {f'<script type="application/ld+json">{faq_schema}</script>' if faq_schema else ''}
</head>
<body>
  {construire_header(archi, "secondaire", pilier['id'])}
  <main class="container">
    <nav class="fil-ariane">
      <a href="../../index.html">Accueil</a> ›
      <a href="../../piliers/{pilier['slug']}.html">{pilier['titre']}</a> ›
      <span>{secondaire['titre']}</span>
    </nav>
    <div class="page-layout">
      <article class="contenu-principal">
        <img src="{img['url']}" alt="{h1}" class="article-img" loading="lazy" width="1200">
        <p class="image-credit">Image générée par IA pour illustration</p>
        <h1>{h1}</h1>
        <p class="intro">{intro}</p>
        <div class="article-body">{contenu}</div>
        {bloc_adsense(ADSENSE_SLOT_MILIEU, "inArticle")}
        <div class="faq-section">
          <h2>Questions fréquentes</h2>{faq_html}
        </div>
        <div class="articles-connexes">
          <h2>Articles de blog sur ce sujet</h2>
          {arts_connexes}
        </div>
      </article>
      <aside class="sidebar">
        <div class="widget">
          <h3>Guide {pilier['titre']}</h3>
          <a href="../../piliers/{pilier['slug']}.html">← Retour au guide complet</a>
          <h4 style="margin:12px 0 8px;font-size:.9rem;color:var(--vert)">Pages du guide</h4>
          {liens_soeurs}
        </div>
        {bloc_adsense(ADSENSE_SLOT_SIDEBAR, "sidebar")}
      </aside>
    </div>
  </main>
  {construire_footer("secondaire")}
  <script>const PILIER_ID="{pilier['id']}"; const PAGE_SLUG="{secondaire['slug']}";</script>
  <script src="../../main.js"></script>
</body></html>"""

    Path(f"secondaires/{pilier['id']}/{secondaire['slug']}.html").write_text(html, encoding="utf-8")

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

    img = get_image(f"pergola {sujet.get('mot_cle','jardin')}", modele="schnell")

    # Ancres diversifiées
    ancre_pilier = ""
    ancre_sec    = ""
    url_pilier   = ""
    url_sec      = ""
    if pilier_parent and comments_config:
        ancre_pilier = ancre_aleatoire(pilier_parent['id'], comments_config)
        url_pilier   = f"../../piliers/{pilier_parent['slug']}.html"
    if secondaire_parent and pilier_parent:
        ancre_sec = secondaire_parent.get('mot_cle', secondaire_parent['titre'])
        url_sec   = f"../../secondaires/{pilier_parent['id']}/{secondaire_parent['slug']}.html"

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

    prompt = f"""Tu es expert SEO et rédacteur web pergolas France.
Article de blog optimisé SEO ET Google Discover sur : {sujet['titre']}
Mot-clé cible : {sujet['mot_cle']}
{kw_block}
{maillage_instructions}

CONSIGNES :
- Titre accrocheur façon Discover (curiosité, utilité, émotion)
- Français naturel, pratique, 900-1100 mots
- Prix euros, conseils marché France
- Structure : H1 avec mot-clé, 4-5 H2, listes <ul>
- Les liens de maillage doivent être dans le corps du texte, pas dans une section séparée

Format STRICT :
<META>description 155 car.</META>
<INTRO>2-3 phrases d'accroche</INTRO>
<CONTENU>[HTML complet avec les liens de maillage intégrés dans les paragraphes]</CONTENU>
<FAQ1Q>question</FAQ1Q><FAQ1R>réponse</FAQ1R>
<FAQ2Q>question</FAQ2Q><FAQ2R>réponse</FAQ2R>
<FAQ3Q>question</FAQ3Q><FAQ3R>réponse</FAQ3R>"""

    texte   = appeler_claude(prompt, max_tokens=2500)
    meta    = extraire_balise(texte, "META") or sujet["titre"]
    intro   = extraire_balise(texte, "INTRO") or ""
    contenu = extraire_balise(texte, "CONTENU") or ""

    qrs      = []
    faq_html = ""
    for i in range(1, 4):
        q = extraire_balise(texte, f"FAQ{i}Q")
        r = extraire_balise(texte, f"FAQ{i}R")
        if q:
            qrs.append({"q": q, "r": r})
            faq_html += f'<div class="faq-item"><button class="faq-question">{q}</button><div class="faq-reponse">{r}</div></div>\n'

    date_iso = datetime.now().strftime("%Y-%m-%d")

    # Articles similaires (chargés depuis articles.json existant)
    articles_existants = charger_articles()
    similaires_html    = generer_articles_similaires(
        sujet["slug"], sujet.get("pilier_id", ""), articles_existants
    )

    # Schemas
    breadcrumb_items = [{"name": "Accueil", "url": f"{SITE_URL}/index.html"}]
    if pilier_parent:
        breadcrumb_items.append({
            "name": pilier_parent["titre"],
            "url": f"{SITE_URL}/piliers/{pilier_parent['slug']}.html"
        })
    breadcrumb_items.append({
        "name": sujet["titre"],
        "url": f"{SITE_URL}/blog/{sujet['slug']}.html"
    })

    breadcrumb_schema = schema_breadcrumb(breadcrumb_items)
    faq_schema        = schema_faq(qrs)
    article_schema    = schema_article(
        sujet["titre"], meta, img["url"],
        date_published=date_iso, date_modified=date_iso
    )

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{sujet['titre']} | {SITE_NOM}</title>
  <meta name="description" content="{meta}">
  {meta_commune()}
  <link rel="canonical" href="{SITE_URL}/blog/{sujet['slug']}.html">
  <link rel="stylesheet" href="../../style.css">
  <script type="application/ld+json">{article_schema}</script>
  <script type="application/ld+json">{breadcrumb_schema}</script>
  {f'<script type="application/ld+json">{faq_schema}</script>' if faq_schema else ''}
</head>
<body>
  {construire_header(archi, "blog", sujet.get('pilier_id'))}
  <main class="container">
    <nav class="fil-ariane">
      <a href="../../index.html">Accueil</a> ›
      {f"<a href='../../piliers/{pilier_parent['slug']}.html'>{pilier_parent['titre']}</a> ›" if pilier_parent else ""}
      <span>{sujet['titre']}</span>
    </nav>
    <div class="page-layout">
      <article class="contenu-principal">
        <span class="categorie">{sujet.get('categorie','Blog')}</span>
        <h1>{sujet['titre']}</h1>
        <p class="intro">{intro}</p>
        <img src="{img['url']}" alt="{sujet['titre']}" class="article-img" loading="lazy" width="1200">
        <p class="image-credit">Image générée par IA pour illustration</p>
        {bloc_adsense(ADSENSE_SLOT_MILIEU, "inArticle")}
        <div class="article-body">{contenu}</div>
        <div class="faq-section">
          <h2>Questions fréquentes</h2>{faq_html}
        </div>
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
  <script src="../../main.js"></script>
</body></html>"""

    Path(f"blog/{sujet['slug']}.html").write_text(html, encoding="utf-8")

    # Mise à jour articles.json
    index_file = Path("articles.json")
    articles   = json.loads(index_file.read_text(encoding="utf-8")) if index_file.exists() else []
    
    # Récupérer thumb Unsplash pour les vignettes (Replicate = URL temporaire)
    thumb_img = recuperer_image_unsplash(f"pergola {sujet.get('mot_cle','jardin')}")
    
    articles.insert(0, {
        "slug": sujet["slug"],
        "titre": sujet["titre"],
        "categorie": sujet.get("categorie","Blog"),
        "description": meta,
        "date": date_iso,
        "thumb": thumb_img.get("url","").replace("w=1200","w=400"),
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
    generer_sitemap(archi, articles)
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
def generer_page_blog(archi, articles):
    cards = ""
    for art in articles[:50]:
        thumb = art.get("thumb","")
        img   = f'<img src="{thumb}" alt="{art["titre"]}" class="card-image" loading="lazy">' if thumb else ""
        cards += f"""
    <a href="blog/{art['slug']}.html" class="article-card">
      {img}
      <div class="card-body">
        <span class="categorie">{art['categorie']}</span>
        <h2>{art['titre']}</h2>
        <p>{art.get('description','')[:100]}...</p>
      </div>
    </a>"""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Blog Pergola | {SITE_NOM}</title>
  <meta name="description" content="Tous nos articles et conseils sur les pergolas en France.">
  {meta_commune()}
  <link rel="stylesheet" href="style.css">
</head>
<body>
  {construire_header(archi, "racine")}
  <main class="container">
    <h1 style="font-family:Georgia,serif;color:var(--vert);padding:40px 0 24px;">Blog & Conseils Pergola</h1>
    <div class="articles-grid">{cards}</div>
  </main>
  {construire_footer("racine")}
  <script src="main.js"></script>
</body></html>"""
    Path("blog.html").write_text(html, encoding="utf-8")

# ─── SITEMAP ──────────────────────────────────────────────
def generer_sitemap(archi, articles):
    urls = [f'<url><loc>{SITE_URL}/index.html</loc><priority>1.0</priority><changefreq>daily</changefreq></url>']
    for p in archi["piliers"]:
        urls.append(f'<url><loc>{SITE_URL}/piliers/{p["slug"]}.html</loc><priority>0.9</priority><changefreq>monthly</changefreq></url>')
        for s in p["secondaires"]:
            urls.append(f'<url><loc>{SITE_URL}/secondaires/{p["id"]}/{s["slug"]}.html</loc><priority>0.8</priority><changefreq>monthly</changefreq></url>')
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

# ─── MAIN ─────────────────────────────────────────────────
def main():
    import sys
    archi           = charger_architecture()
    keywords        = charger_keywords()
    comments_config = charger_comments_config()
    mode = sys.argv[1] if len(sys.argv) > 1 else "blog"

    if mode == "full":
        print("🚀 Construction complète du site...")
        for d in ["piliers", "secondaires", "blog"]:
            Path(d).mkdir(exist_ok=True)

        generer_accueil(archi)
        articles = charger_articles()

        for pilier in archi["piliers"]:
            generer_page_pilier(pilier, archi, keywords, articles)
            Path(f"secondaires/{pilier['id']}").mkdir(exist_ok=True)
            for secondaire in pilier["secondaires"]:
                generer_page_secondaire(secondaire, pilier, archi, keywords, articles)

        generer_page_blog(archi, articles)
        generer_sitemap(archi, articles)
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

if __name__ == "__main__":
    main()
wc -l /home/claude/build_site_final.py
