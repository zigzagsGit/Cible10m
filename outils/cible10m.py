#!/usr/bin/env python3
"""
cible10m.py - Detection et cotation des impacts sur cible 10 m (ISSF) a partir d'une photo.

Usage :
    python cible10m.py apres.jpg                      # detection sur une seule image
    python cible10m.py apres.jpg --ref avant.jpg      # detection par difference avant/apres (plus fiable)
    python cible10m.py apres.jpg --type pistolet --out resultat.png --json resultat.json

Principe :
    1. On trouve le visuel noir (le plus grand disque sombre) et on y ajuste une ellipse.
    2. On redresse l'image : l'ellipse devient un cercle, avec une echelle fixe en px/mm
       (le diametre du visuel noir est connu : 30,5 mm carabine, 59,5 mm pistolet).
    3. On cherche les trous :
         - avec --ref : difference entre l'image avant et l'image apres (recalees par ECC) ;
         - sans --ref : zones claires dans le noir + zones sombres dans le blanc,
           apres une ouverture morphologique qui efface les lignes des zones.
    4. Pour chaque trou : centre (centroide), distance au centre, points entiers et decimaux.

Limites : photo prise a peu pres de face (l'ellipse corrige une inclinaison moderee, pas une
forte perspective) ; deux plombs dans le meme trou ne donnent qu'un seul impact (signale si
le trou est nettement plus gros qu'un plomb).
"""
import argparse
import json
import math
import sys

import cv2
import numpy as np

# --- Geometrie ISSF (en mm) -------------------------------------------------------------
CIBLES = {
    # r10 : rayon exterieur de la zone 10 ; pas : ecart de rayon entre deux zones
    "carabine": {"noir_diam": 30.5, "r10": 0.25, "pas": 2.5, "px_mm": 20, "noir_zones": (4, 9)},
    "pistolet": {"noir_diam": 59.5, "r10": 5.75, "pas": 8.0, "px_mm": 8, "noir_zones": (7, 10)},
}
R_PLOMB = 2.25  # calibre 4,5 mm


def rayon_zone(cfg, k):
    """Rayon exterieur de la zone k (1..10)."""
    return cfg["r10"] + (10 - k) * cfg["pas"]


def coter(cfg, d):
    """Points entiers et decimaux pour un plomb dont le centre est a d mm du centre.
    Un tir compte la zone dont il touche la ligne (bord du plomb)."""
    entier = 0
    for k in range(10, 0, -1):
        if d - R_PLOMB <= rayon_zone(cfg, k):
            entier = k
            break
    if entier == 0:
        return 0, 0.0
    dec = 11 - (d - R_PLOMB - cfg["r10"] + cfg["pas"]) / cfg["pas"]
    dec = math.floor(min(dec, 10.9) * 10 + 1e-9) / 10  # ISSF : on tronque au dixieme
    return entier, dec


# --- 1. Localisation du visuel noir -------------------------------------------------------
def trouver_visuel(gris):
    flou = cv2.GaussianBlur(gris, (5, 5), 0)
    _, noir = cv2.threshold(flou, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    noir = cv2.morphologyEx(noir, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    # RETR_LIST : le visuel peut etre "dans un trou" d'une zone sombre (fond derriere la carte)
    contours, _ = cv2.findContours(noir, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    h, w = gris.shape
    meilleur, score_max = None, 0
    for c in contours:
        if len(c) < 20:
            continue
        x, y, cw, ch = cv2.boundingRect(c)
        if x <= 1 or y <= 1 or x + cw >= w - 1 or y + ch >= h - 1:
            continue  # touche le bord : probablement le fond, pas le visuel
        coque = cv2.convexHull(c)  # la coque bouche les encoches faites par les trous en bordure
        aire = cv2.contourArea(coque)
        perim = cv2.arcLength(coque, True)
        if aire < 0.002 * h * w or perim == 0:
            continue
        interieur = np.zeros_like(noir)
        cv2.drawContours(interieur, [c], -1, 255, -1)
        if cv2.mean(noir, interieur)[0] < 0.7 * 255:
            continue  # contour d'une zone claire (la carte elle-meme), pas un disque noir
        circ = 4 * math.pi * aire / perim ** 2
        if circ > 0.8 and aire * circ > score_max:
            meilleur, score_max = c, aire * circ
    if meilleur is None:
        raise RuntimeError("Visuel noir introuvable : verifier le cadrage et l'eclairage.")
    return ellipse_robuste(meilleur.reshape(-1, 2).astype(np.float64))


def matrice_cercle(ellipse, diam_px):
    """Matrice 2x2 qui transforme l'ellipse en cercle de diametre diam_px, sans rotation."""
    (_, _), (ew, eh), ang = ellipse
    t = math.radians(ang)
    R = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    return R @ np.diag([diam_px / ew, diam_px / eh]) @ R.T


def ellipse_robuste(pts, iterations=4, tolerance=0.025):
    """Ajuste une ellipse en ecartant les points aberrants (trous qui mordent sur le bord,
    plomb a cheval sur la limite du visuel...)."""
    garde = pts
    ell = cv2.fitEllipse(cv2.convexHull(pts.astype(np.float32)))
    for _ in range(iterations):
        A = matrice_cercle(ell, 1.0)
        r = np.linalg.norm((pts - ell[0]) @ A.T, axis=1) * 2  # 1.0 = sur l'ellipse
        garde = pts[np.abs(r - np.median(r)) < tolerance]
        if len(garde) < 20:
            break
        ell = cv2.fitEllipse(garde.astype(np.float32))
    return ell


# --- 2. Redressement ----------------------------------------------------------------------
def redresser(img, cfg):
    """Retourne l'image redressee (centre de cible au milieu, echelle cfg['px_mm'])."""
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    ell = trouver_visuel(gris)
    k = cfg["px_mm"]
    taille = int(2 * (rayon_zone(cfg, 1) + 8) * k)
    A = matrice_cercle(ell, cfg["noir_diam"] * k)  # etire selon les axes de l'ellipse
    b = np.array([taille / 2, taille / 2]) - A @ np.array(ell[0])
    M = np.hstack([A, b[:, None]])
    out = cv2.warpAffine(img, M, (taille, taille), flags=cv2.INTER_CUBIC,
                         borderMode=cv2.BORDER_REPLICATE)
    return out, M


def recaler(avant, apres):
    """Projette la photo 'avant' dans le repere de la photo 'apres' (homographie par ECC).
    Corrige un leger deplacement de l'appareil entre les deux prises."""
    ga = cv2.cvtColor(avant, cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(apres, cv2.COLOR_BGR2GRAY)
    if ga.shape != gb.shape:
        ga = cv2.resize(ga, gb.shape[::-1])
        avant = cv2.resize(avant, gb.shape[::-1])
    H = np.eye(3, dtype=np.float32)
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-6)
    # Grossier sur image reduite, puis affinage pleine resolution
    for f in (0.25, 1.0):
        a = cv2.GaussianBlur(cv2.resize(ga, None, fx=f, fy=f), (5, 5), 0).astype(np.float32)
        b = cv2.GaussianBlur(cv2.resize(gb, None, fx=f, fy=f), (5, 5), 0).astype(np.float32)
        S = np.diag([f, f, 1]).astype(np.float32)
        Hf = S @ H @ np.linalg.inv(S)
        try:
            _, Hf = cv2.findTransformECC(b, a, Hf.astype(np.float32), cv2.MOTION_HOMOGRAPHY, crit, None, 5)
            H = np.linalg.inv(S) @ Hf @ S
        except cv2.error:
            pass
    return cv2.warpPerspective(avant, H.astype(np.float64), gb.shape[::-1],
                               flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)


# --- 3. Detection des trous ---------------------------------------------------------------
def masque_trous_simple(gris, cfg):
    k = cfg["px_mm"]
    n = gris.shape[0]
    c = n // 2
    r_noir = int(cfg["noir_diam"] / 2 * k)
    marge = max(2, int(0.5 * k))  # incertitude sur le bord du visuel
    dans_noir = np.zeros_like(gris)
    cv2.circle(dans_noir, (c, c), r_noir - marge, 255, -1)
    dans_blanc = np.full_like(gris, 255)
    cv2.circle(dans_blanc, (c, c), r_noir + marge, 0, -1)
    # On efface les lignes de zones et les chiffres (traits < 1 mm) ; un trou de 4,5 mm survit
    d = int(1.2 * k) | 1
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))
    noir_lisse = cv2.morphologyEx(gris, cv2.MORPH_OPEN, se)    # retire les traits clairs
    blanc_lisse = cv2.morphologyEx(gris, cv2.MORPH_CLOSE, se)  # retire les traits sombres
    # Niveau local du noir et du blanc (eclairage inegal) : moyenne gaussienne normalisee,
    # calculee uniquement sur les pixels de la meme region
    def niveau_local(img, region):
        r = (region > 0).astype(np.float32)
        s = 5.0 * k
        num = cv2.GaussianBlur(img.astype(np.float32) * r, (0, 0), s)
        den = cv2.GaussianBlur(r, (0, 0), s)
        return num / np.maximum(den, 1e-3)
    fond_noir = niveau_local(noir_lisse, dans_noir)
    fond_blanc = niveau_local(blanc_lisse, dans_blanc)
    anneau = np.zeros_like(gris)
    cv2.circle(anneau, (c, c), int(r_noir + 3 * k), 255, int(2 * k))
    niv_blanc = np.median(blanc_lisse[anneau > 0])
    niv_noir = np.median(noir_lisse[cv2.erode(dans_noir, None, iterations=int(3 * k)) > 0])
    contraste = max(30, niv_blanc - niv_noir)
    # Le noir est tres uniforme apres lissage : un seuil bas suffit et attrape les trous peu contrastes
    m1 = (noir_lisse - fond_noir > 0.12 * contraste) & (dans_noir > 0)     # trous clairs dans le noir
    m2 = (fond_blanc - blanc_lisse > 0.25 * contraste) & (dans_blanc > 0)  # trous sombres dans le blanc
    m = ((m1 | m2) * 255).astype(np.uint8)
    # Recoud un trou coupe en deux par la bande d'incertitude du bord
    d2 = (2 * marge + 3) | 1
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d2, d2)))


def masque_trous_diff(ref, gris):
    diff = cv2.GaussianBlur(cv2.absdiff(ref, gris), (5, 5), 0)
    p5, p95 = np.percentile(gris, (5, 95))
    seuil = max(20, 0.12 * (p95 - p5))
    return ((diff > seuil) * 255).astype(np.uint8)


def extraire_impacts(masque, cfg):
    k = cfg["px_mm"]
    # Ouverture avec un disque de ~3 mm : efface les lignes de zones et les chiffres
    d = max(3, int(3.0 * k)) | 1
    disque = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))
    m = cv2.morphologyEx(masque, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, disque)
    aire_plomb = math.pi * (R_PLOMB * k) ** 2
    c0 = m.shape[0] / 2
    n, lab, stats, cent = cv2.connectedComponentsWithStats(m)
    impacts = []
    for i in range(1, n):
        aire = stats[i, cv2.CC_STAT_AREA]
        if aire < 0.35 * aire_plomb or aire > 12 * aire_plomb:
            continue
        # Trou plus gros qu'un plomb : plusieurs impacts qui se chevauchent -> k-means
        nb = max(1, int(round(aire / (0.85 * aire_plomb)))) if aire > 1.4 * aire_plomb else 1
        if nb == 1:
            centres = [cent[i]]
        else:
            ys, xs = np.nonzero(lab == i)
            pts = np.float32(np.column_stack([xs, ys]))
            _, _, cc = cv2.kmeans(pts, nb, None, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 50, 0.1),
                                  5, cv2.KMEANS_PP_CENTERS)
            centres = list(cc)
        for cx, cy in centres:
            cx, cy = float(cx), float(cy)
            x_mm = (cx - c0) / k
            y_mm = -(cy - c0) / k  # y vers le haut
            d = math.hypot(x_mm, y_mm)
            if d - R_PLOMB > rayon_zone(cfg, 1) + 3:
                continue  # hors cible
            entier, dec = coter(cfg, d)
            impacts.append({
                "x_mm": round(x_mm, 2), "y_mm": round(y_mm, 2), "distance_mm": round(d, 2),
                "points": entier, "decimal": dec, "trou_groupe": nb > 1,
                "px": (float(cx), float(cy)),
            })
    impacts.sort(key=lambda t: t["distance_mm"])
    return impacts


# --- 4. Sortie ----------------------------------------------------------------------------
def annoter(img, impacts, cfg):
    out = img.copy() if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    k = cfg["px_mm"]
    c = out.shape[0] // 2
    for z in range(1, 11):
        cv2.circle(out, (c, c), int(round(rayon_zone(cfg, z) * k)), (0, 200, 255), 1, cv2.LINE_AA)
    for n, t in enumerate(impacts, 1):
        p = (int(round(t["px"][0])), int(round(t["px"][1])))
        cv2.circle(out, p, int(R_PLOMB * k), (0, 0, 255), 2, cv2.LINE_AA)
        cv2.drawMarker(out, p, (0, 0, 255), cv2.MARKER_CROSS, int(k), 1)
        cv2.putText(out, f"{n}:{t['decimal']}", (p[0] + int(2.6 * k), p[1]),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.03 * k, (255, 0, 0), max(1, k // 10), cv2.LINE_AA)
    return out


def analyser(chemin, type_cible="carabine", chemin_ref=None):
    cfg = CIBLES[type_cible]
    img = cv2.imread(chemin)
    if img is None:
        raise FileNotFoundError(chemin)
    rect, M = redresser(img, cfg)
    gris = cv2.cvtColor(rect, cv2.COLOR_BGR2GRAY)
    if chemin_ref:
        avant = cv2.imread(chemin_ref)
        if avant is None:
            raise FileNotFoundError(chemin_ref)
        # On recale 'avant' sur 'apres', puis on lui applique exactement le meme redressement
        avant = recaler(avant, img)
        ref = cv2.warpAffine(cv2.cvtColor(avant, cv2.COLOR_BGR2GRAY), M, gris.shape[::-1],
                             flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        masque = masque_trous_diff(ref, gris)
    else:
        masque = masque_trous_simple(gris, cfg)
    impacts = extraire_impacts(masque, cfg)
    return impacts, annoter(rect, impacts, cfg)


def main():
    ap = argparse.ArgumentParser(description="Detection d'impacts sur cible 10 m ISSF")
    ap.add_argument("image", help="photo de la cible apres le(s) tir(s)")
    ap.add_argument("--ref", help="photo de la meme cible avant le tir (mode difference)")
    ap.add_argument("--type", choices=CIBLES, default="carabine")
    ap.add_argument("--out", default="resultat.png", help="image annotee")
    ap.add_argument("--json", help="fichier JSON des impacts")
    a = ap.parse_args()
    try:
        impacts, annotee = analyser(a.image, a.type, a.ref)
    except (RuntimeError, FileNotFoundError) as e:
        sys.exit(f"Erreur : {e}")
    cv2.imwrite(a.out, annotee)
    total, total_dec = 0, 0.0
    print(f"{'#':>2}  {'x mm':>7} {'y mm':>7} {'dist':>6}  pts  dec")
    for n, t in enumerate(impacts, 1):
        total += t["points"]
        total_dec += t["decimal"]
        alerte = "  (trou groupe : position estimee)" if t["trou_groupe"] else ""
        print(f"{n:>2}  {t['x_mm']:>7.2f} {t['y_mm']:>7.2f} {t['distance_mm']:>6.2f}  {t['points']:>3}  {t['decimal']:>4}{alerte}")
    print(f"Total : {total} / {total_dec:.1f} sur {len(impacts)} impact(s) - image : {a.out}")
    if a.json:
        with open(a.json, "w") as f:
            json.dump([{k: v for k, v in t.items() if k != "px"} for t in impacts], f, indent=2)


if __name__ == "__main__":
    main()
