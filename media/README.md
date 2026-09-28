# Audio Mixer artwork

This illustration belongs to the BloxSmith industrial pixel-art block family.
It communicates the block's function; it is not a screenshot of Studio or a
promise of additional runtime features.

## Files

- `cover.png`: original square PNG cover, preserved without retouching.
- `thumbnail.webp`: 320 × 320 WebP derivative for README and catalog cards.
- Accent: Amber / orange.
- Meaning: Multiple independent Opus sources are mixed into one stream, with per-source gain and mute controls.

The module's silhouette, viewpoint, light, framing and steel/graphite housing are
shared with the other pilot blocks. A large roof symbol and a single English title
provide identification without relying only on color. Descriptive alt text must
accompany the image wherever it is rendered.

These are documentation assets, not executable UI assets. Their presence does
not automatically register them in Studio or the public compatibility catalog.
The block version and runtime contract remain unchanged.

## Provenance

Created on 2026-09-27 with the built-in image generation tool, using owner-supplied
visual references. No image API key or CLI fallback was used.
Owner-supplied HTML Display and Audio Record compact illustrations from the HackInvent block reference library. The references guide the housing, composition and audio accent; they are not included in this repository.

The selected generated PNG was copied byte for byte. Only the thumbnail was
resized and encoded; no text, recoloring or compositing was applied afterwards.
The artwork is distributed under this repository's [Apache-2.0 license](../LICENSE).

Thumbnail export with ImageMagick:

```sh
convert media/cover.png -thumbnail 320x320 -strip -quality 88 -define webp:method=6 media/thumbnail.webp
```

## Generation prompt

The following is the exact prompt used for the selected cover. Generation is
not deterministic; retain this selected cover as the reference for future edits.

```text
Use case: stylized-concept.
Asset type: a square cover illustration for the Audio Mixer software block in a coherent BloxSmith block catalog.
Input images: Image 1 (HTML Display) is the reference for the industrial cube geometry, front/top/right three-quarter viewpoint, framing, white background and restrained pixel-art finish. Image 2 (Audio Record compact) is a supporting reference for the warm orange audio-family accent and readable hardware controls. These are visual references, not content to reproduce.
Primary request: create ONE new AUDIO MIXER block illustration in that same modular family. This block mixes multiple independent audio sources into a single audio stream; it has gain and mute settings, but is not a microphone, recorder, transcription service, DJ deck, or speaker.
Scene/backdrop: a clean near-white background, a subtle small grounded shadow, no environment or props.
Subject: one compact, near-cubical dark graphite industrial module, reinforced brushed-steel corners, a few deliberate vents and connectors. On the roof, one LARGE unmistakable three-fader mixer symbol in warm amber/orange. On the front, a wide title plate reading exactly "AUDIO MIXER" in crisp white uppercase pixel lettering. Below it, one simple high-contrast display depicting three small separate waveform lanes converging into ONE output waveform. Below the display, three large simple gain sliders with different positions, plus small mute indicator squares; no labels. The right panel has a restrained vertical accent strip and a small row of generic connectors, not a second scene.
Style/medium: polished detailed pixel-art industrial product illustration, deliberate stepped edges and controlled pixel clusters, tactile metal surfaces, readable bold silhouettes. Match the restrained craft of Image 1, not neon overload and not smooth photorealistic 3D.
Composition/framing: 1024 x 1024 square, one isolated object fully visible, centered, approximately 84 percent of canvas, consistent clear margins on every edge. The main front face, roof and right face are visible exactly as in Image 1. Upper-left soft light, subtle lower-right shadow.
Color palette: charcoal and graphite, cool steel edge details, one dominant warm amber/orange accent. Mostly dark housing with sparse bright functional accents.
Text (verbatim): "AUDIO MIXER" only, exactly once, prominent and legible. No subtitles, tiny writing, format labels, version numbers, badges or slogans.
Constraints: the roof symbol, title and functional display must remain identifiable in a 320 px thumbnail. Use a tidy hierarchy and plenty of breathing room. No cats, people, desk, floating extras, detached modules, brand logos, microphones, recording icons, OCR, music notes, watermark or borders. The output is a finished standalone image, not a collage or UI screenshot.
```
