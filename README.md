<p align="center">
  <img src="assets/logo/logo.svg" alt="CiboUniPI Logo" width="200">
</p>

<h1 align="center"> MENSE </h1>

<p align="center">Un bot Telegram per consultare i menù, gli orari e le tariffe delle mense universitarie di Pisa (DSU Toscana).</p>

<p align="center">Il bot supporta la ricerca inline, la navigazione giornaliera dei menù, il calcolo delle tariffe su base ISEE e la consultazione degli orari in tempo reale.</p>

## Indice

- [Indice](#indice)
- [Struttura del progetto](#struttura-del-progetto)
- [Flowchart](#flowchart)
  - [Flusso Dati](#flusso-dati)
- [Funzionalità](#funzionalità)
  - [Ricerca Inline](#ricerca-inline)
  - [Menu e Navigazione](#menu-e-navigazione)
  - [Info e Orari](#info-e-orari)
  - [Tariffe ISEE](#tariffe-isee)
  - [Automazione Social (Instagram)](#automazione-social-instagram)
    - [Pattern Generativi disponibili per i post](#pattern-generativi-disponibili-per-i-post)
- [Comandi](#comandi)
- [Data Sources](#data-sources)
- [Problemi noti](#problemi-noti)

<!--

[<img src="https://wsrv.nl/?url=github.com/plumkewe.png?w=64&h=64&mask=circle&fit=cover" width="46" height="46" alt="Lyubomyr Malay" />](https://github.com/plumkewe)

-->

<h2 align="right"> SCREENSHOT </h2>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/bot-b.JPEG">
    <source media="(prefers-color-scheme: light)" srcset="assets/screenshots/bot-w.JPEG">
    <img src="assets/screenshots/bot-w.JPEG" alt="Screenshot del bot">
  </picture>
</p>

## Struttura del progetto

<p align="right">(<a href="#indice">indice</a>)</p>

```graphql
├── README.md
├── requirements.txt
├── assets/
│   ├── icons/
│   ├── img/
│   ├── logo/
│   └── posts/                <- immagini generate per i post di Instagram
├── cloudflare-worker/        <- microservizio per lo scheduler preciso (gestisce fuso orario IT)
├── data/
│   ├── canteens.json         <- dati delle mense (orari, servizi, coordinate)
│   ├── combinations.json     <- combinazioni di piatti (es. menu fisso)
│   ├── cookies.txt           <- sessione per lo scraping
│   ├── menu.json             <- menù aggiornato quotidianamente
│   └── rates.json            <- tariffe per fascia ISEE
├── bot.py                    <- entrypoint del bot Telegram
├── scripts/
│   ├── extract_menu.py       <- scraper menù da canteen.dsutoscana.cloud
│   ├── fetch_rates.py        <- scraper tariffe DSU
│   ├── generate_menu_images.py <- genera i post immagine in HTML/ststili (Playwright)
│   ├── publish_instagram.py  <- pubblica Carousel su Instagram tramite Graph API
│   └── smart_update.py       <- aggiornamento intelligente dei dati testuali
└── .github/
    └── workflows/
        ├── update_menu.yml       <- aggiornamento giornaliero menù testuale
        ├── generate_images.yml   <- crea e salva le immagini dei post
        ├── publish_instagram.yml <- invia le immagini create su IG
        └── update_rates.yml      <- aggiornamento tariffe
```

## Flowchart

<p align="right">(<a href="#indice">indice</a>)</p>

### Flusso Dati

```mermaid
graph LR
    A["canteen.dsutoscana.cloud"] --> B["menu.json"]
    C["DSU Toscana - Tariffe"] --> D["rates.json"]
    E["canteens.json"] -->|Dati statici mense| F["bot.py"]

    G["Cloudflare Worker<br>(Scheduler ITEsatto)"] -->|Trigger workflow| H{"GitHub Actions"}

    H -->|update_menu| B
    H -->|update_rates| D
    B -->|generate_images| I["Immagini Post (.png)"]
    H -->|publish_instagram| J["Instagram @mense.unipi"]
    I --> J

    B --> F
    D --> F
    K["combinations.json"] --> F

    F -->|"Menù / Orari / Tariffe"| L["Utente Telegram"]
    L -->|"@cibounipibot"| F
```

## Funzionalità

<p align="right">(<a href="#indice">indice</a>)</p>

### Ricerca Inline

È possibile cercare un piatto specifico (es. `p:Arista`) direttamente in qualsiasi chat Telegram senza aprire il bot. I risultati mostrano in quali mense e in quali giorni verrà servito il piatto cercato, con navigazione tra le date.

La ricerca inline si avvia digitando `@cibounipibot` seguito da uno spazio e dalla query. Senza prefisso viene mostrata direttamente la lista delle mense per vedere il menù di oggi.

### Menu e Navigazione

Una volta aperto il menù di una mensa, è possibile:

- Scorrere i giorni con i pulsanti ◀︎ e ▶︎
- Tornare ad oggi con il pulsante ○
- Alternare tra **Pranzo** e **Cena**
- Filtrare per mensa specifica oppure visualizzare **TUTTE** le mense insieme

Per le mense TUTTE, ogni piatto disponibile solo in alcune mense viene annotato con `(Solo NomeMensa)`.

### Info e Orari

Digitando `@cibounipibot i:` è possibile consultare lo stato attuale di ogni mensa (aperta/chiusa), gli orari di pranzo e cena e i servizi disponibili (pizzeria, prendi e vai, menù vegetariano, gluten-free, ecc.).

Il pulsante **APERTE ORA** nella tastiera persistente mostra subito le mense attualmente operative.

### Tariffe ISEE

Digitando `@cibounipibot t:` viene mostrata la tabella completa delle tariffe per fascia ISEE.

Digitando `@cibounipibot t:<valore>` (es. `t:20000`) il bot calcola automaticamente la fascia di appartenenza e mostra la tariffa personalizzata per pranzo, cena e colazione.

### Automazione Social (Instagram)

Oltre al bot Telegram, il progetto include un sistema automatizzato per la **pubblicazione giornaliera dei menù su Instagram**. L'infrastruttura è basata su GitHub Actions suddivise in tre fasi:

1. **`update_menu.yml`**: Scarica i testi aggiornati dei menù salvandoli in `menu.json`.
2. **`generate_images.yml`**: Tramite uno script Python nativo (`generate_menu_images.py`), il sistema genera le grafiche ("slide") a partire da template, scrivendo testo personalizzato e uno sfondo procedurale con geometrie dinamiche e vibranti. **Il design cambia dinamicamente** e il sistema alterna vari colori e pattern su base settimanale e giornaliera.
3. **`publish_instagram.yml`**: Utilizzando le **Graph API di Meta**, le immagini generate vengono raggruppate e pubblicate come "Carousel" sul profilo Instagram dedicato ai menù.

#### Pattern Generativi disponibili per i post

| Dot Grid | Diagonal Stripes | Crosshatch | Diamond Grid | Hexagons |
| :---: | :---: | :---: | :---: | :---: |
| <img src="assets/img/patterns/dot_grid.png" width="88" height="88" style="aspect-ratio:1/1;"> | <img src="assets/img/patterns/diagonal_stripes.png" width="88" height="88" style="aspect-ratio:1/1;"> | <img src="assets/img/patterns/crosshatch.png" width="88" height="88" style="aspect-ratio:1/1;"> | <img src="assets/img/patterns/diamond_grid.png" width="88" height="88" style="aspect-ratio:1/1;"> | <img src="assets/img/patterns/hexagons.png" width="88" height="88" style="aspect-ratio:1/1;"> |
| **Zigzag** | **Concentric Circles** | **Plus Grid** | **Waves** | **Triangles** |
| <img src="assets/img/patterns/zigzag.png" width="88" height="88" style="aspect-ratio:1/1;"> | <img src="assets/img/patterns/concentric_circles.png" width="88" height="88" style="aspect-ratio:1/1;"> | <img src="assets/img/patterns/plus_grid.png" width="88" height="88" style="aspect-ratio:1/1;"> | <img src="assets/img/patterns/waves.png" width="88" height="88" style="aspect-ratio:1/1;"> | <img src="assets/img/patterns/triangles.png" width="88" height="88" style="aspect-ratio:1/1;"> |
| **Squares** | **Hollow Dots** | **X Shapes** | **Vertical Stripes** | **Horizontal Stripes** |
| <img src="assets/img/patterns/squares.png" width="88" height="88" style="aspect-ratio:1/1;"> | <img src="assets/img/patterns/hollow_dots.png" width="88" height="88" style="aspect-ratio:1/1;"> | <img src="assets/img/patterns/x_shapes.png" width="88" height="88" style="aspect-ratio:1/1;"> | <img src="assets/img/patterns/vertical_stripes.png" width="88" height="88" style="aspect-ratio:1/1;"> | <img src="assets/img/patterns/horizontal_stripes.png" width="88" height="88" style="aspect-ratio:1/1;"> |

Per far sì che l'esecuzione di questi workflow sia precisa e rispetti l'orario italiano (gestendo in automatico il cambio tra ora legale e solare), i comandi vengono avviati da uno scheduler configurato tramite **Cloudflare Workers**. Questo risolve i noti problemi di ritardo e imprecisione dei classici `cron` integrati nativamente in GitHub Actions.

## Comandi

<p align="right">(<a href="#indice">indice</a>)</p>

<table>
  <thead>
    <tr>
      <th>Funzione</th>
      <th>Comando</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><b>Menu di Oggi</b><br>Seleziona una mensa e vedi il menù del giorno</td>
      <td><code>@cibounipibot</code> (+ spazio)</td>
    </tr>
    <tr>
      <td><b>Cerca Piatto</b><br>Cerca un piatto per nome in tutte le mense e tutti i giorni</td>
      <td><code>@cibounipibot p:nome piatto</code></td>
    </tr>
    <tr>
      <td><b>Info & Orari</b><br>Stato e orari di una mensa specifica</td>
      <td><code>@cibounipibot i:</code></td>
    </tr>
    <tr>
      <td><b>Tariffe ISEE</b><br>Tabella completa delle tariffe</td>
      <td><code>@cibounipibot t:</code></td>
    </tr>
    <tr>
      <td><b>Tariffa Personalizzata</b><br>Calcola la tariffa per il tuo ISEE</td>
      <td><code>@cibounipibot t:&lt;valore&gt;</code><br>es. <code>t:20000</code></td>
    </tr>
    <tr>
      <td><b>Aperte Ora</b><br>Lista mense aperte in questo momento (tastiera persistente)</td>
      <td>Pulsante <code>APERTE ORA</code></td>
    </tr>
    <tr>
      <td><b>Seleziona Mensa</b></td>
      <td><code>/menu</code></td>
    </tr>
    <tr>
      <td><b>Link Utili DSU</b></td>
      <td><code>/links</code></td>
    </tr>
    <tr>
      <td><b>Guida all'uso</b></td>
      <td><code>/help</code></td>
    </tr>
    <tr>
      <td><b>Benvenuto</b></td>
      <td><code>/start</code></td>
    </tr>
  </tbody>
</table>

## Data Sources

<p align="right">(<a href="#indice">indice</a>)</p>

<table>
  <thead>
    <tr>
      <th align="left">Tipologia Dati</th>
      <th align="left">Fonte Principale</th>
      <th align="left">Dettagli / Link</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Menù Mense</strong></td>
      <td>DSU Toscana — canteen.dsutoscana.cloud</td>
      <td><a href="https://canteen.dsutoscana.cloud/menu" target="_blank">canteen.dsutoscana.cloud/menu</a> — aggiornato quotidianamente via GitHub Actions</td>
    </tr>
    <tr>
      <td><strong>Tariffe ISEE</strong></td>
      <td>DSU Toscana — sito istituzionale</td>
      <td><a href="https://www.dsu.toscana.it" target="_blank">dsu.toscana.it</a></td>
    </tr>
    <tr>
      <td><strong>Dati Mense</strong></td>
      <td>Raccolta manuale + sito DSU</td>
      <td>Orari, servizi e coordinate in <code>canteens.json</code></td>
    </tr>
  </tbody>
</table>

**Hostato su:**

<p align="center">
  <a>
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://cdn.simpleicons.org/render/white">
      <source media="(prefers-color-scheme: light)" srcset="https://cdn.simpleicons.org/render/black">
      <img alt="Render" src="https://cdn.simpleicons.org/render/black" width="32" height="32">
    </picture>
  </a>
</p>

## Problemi noti

- [ ] **Orari mense:** Gli orari sono salvati staticamente in `canteens.json` e potrebbero non riflettere variazioni stagionali o straordinarie.
