# Cible 10 m

Application web installable (Android et iPhone) qui détecte les impacts sur une cible de tir à 10 m (carabine ou pistolet, ISSF) à partir de photos et calcule les points entiers et décimaux.

Tout se passe sur le téléphone : aucune photo n'est envoyée sur un serveur. Les séries sont enregistrées dans le navigateur du téléphone.

## Utiliser l'application

L'application est publiée par GitHub Pages à l'adresse :

```
https://<propriétaire>.github.io/<dépôt>/
```

### L'installer sur le téléphone

- **Android (Chrome)** : ouvrir l'adresse, puis menu ⋮ → « Installer l'application » (ou « Ajouter à l'écran d'accueil »).
- **iPhone (Safari)** : ouvrir l'adresse, bouton Partager → « Sur l'écran d'accueil ».

Une fois installée, elle s'ouvre en plein écran et fonctionne sans réseau au stand (après une première ouverture avec réseau).

### Modes de prise de vue

- **Tir par tir** : téléphone fixe sur un support. Une photo avant le premier tir, puis une après chaque plomb. Les anciens trous et les gommettes, même collées en cours de série, ne sont pas comptés.
- **Photo seule** : photo prise à la main après la série, avec une photo « avant » facultative (conseillée si des trous n'ont pas de gommette).

Dans les deux cas, on peut corriger à la main : toucher la cible pour ajouter un impact, toucher un impact pour l'enlever. La case « Cible simulée » permet d'essayer l'application sans aller au stand.

## Contenu du dépôt

| Fichier | Rôle |
| --- | --- |
| `index.html` | L'application complète (interface + analyse d'image en JavaScript). |
| `manifest.webmanifest` | Nom, couleurs et icônes pour l'installation. |
| `sw.js` | Service worker : fonctionnement hors ligne et mises à jour. |
| `icon-*.png`, `apple-touch-icon.png` | Icônes de l'application (Android, iPhone). |
| `outils/cible10m.py` | Script Python (OpenCV) qui fait la même analyse sur ordinateur, à partir de fichiers photo. |

## Publier une nouvelle version

1. Modifier `index.html` (et augmenter `VERSION` dans le script de l'application).
2. Augmenter `VERSION` dans `sw.js` avec la même valeur : c'est ce qui fait que les téléphones récupèrent la nouvelle version.
3. Pousser sur la branche `main`. GitHub Pages republie en une à deux minutes ; l'application installée se met à jour à l'ouverture suivante (parfois la deuxième).

## Mettre en place GitHub Pages (une seule fois)

Dans le dépôt sur GitHub : **Settings → Pages → Build and deployment** → Source « Deploy from a branch », branche `main`, dossier `/ (root)`, puis **Save**.

## Script Python (ordinateur)

```bash
pip install -r outils/requirements.txt
python outils/cible10m.py apres.jpg                       # une seule photo
python outils/cible10m.py apres.jpg --ref avant.jpg       # différence avant/après (plus fiable)
python outils/cible10m.py apres.jpg --type pistolet --out resultat.png --json resultat.json
```

Le script affiche les impacts trouvés (position, points, décimal) et enregistre une image annotée.

## Tester en local

Le service worker ne fonctionne qu'en HTTPS ou sur `localhost` :

```bash
python -m http.server 8000
```

puis ouvrir `http://localhost:8000/`.
