# Harbor

**Convoys para [Keelokit](https://github.com/leosimini/keelokit): muchas sesiones, un solo push a main.**

*[Read in English](README.md)*

Keelokit construye una historia por sesión y la sube a `main`. Con muchas sesiones, en más de
una cuenta de Claude o en más de una máquina, eso es un verify completo por subida, y nadie ve la
combinación hasta que ya está en `main`. Harbor las agrupa: cada sesión termina en su rama (un
*vessel*), un *skipper* integra el lote en `convoy/<n>`, se verifica una vez y, con el ok del
*harbormaster*, entra a `main` con un solo push.

Lo escribí después de una semana haciendo esto a mano en un monorepo real. El tablero se separó de
la realidad, el «verde» de una rama dejó de corresponder a su último commit y hubo que renombrar
timestamps de migraciones al integrar. Harbor mantiene el proceso y saca el trabajo manual:

- **El estado es una rama de git que solo escribe Harbor** (`harbor/log`): archivos TOML con esquema
  fijo y páginas generadas a partir de ellos, que nadie edita. Nunca está en `main`, así que
  escribirla no mueve `main` ni dispara su CI. Las sesiones de cualquier cuenta o máquina la leen
  con `git fetch`.
- **Una rama entra a un convoy solo con su hash exacto y un resultado de verify para ese hash.** Un
  commit posterior no tiene resultado: la entrega no vale hasta que se vuelva a verificar.
- **Las rutas calientes compartidas van de a una.** Dos ramas que tocan el mismo hotspot declarado
  (schema, migraciones, tipos compartidos, textos) nunca están juntas en convoys abiertos.
- **Un solo harbormaster a la vez, con un heartbeat que vence.** Cuando vence, cualquier sesión puede
  tomar la guardia, y gana el primer commit.
- **Las cuentas tienen un tope de sesiones y una pausa.** Cuando una cuenta llega a su límite, sus
  sesiones traspasan lo que empujaron, con hashes, en lugar de dejar trabajo a medias.

## Estado

Versión 0.1.0, sin publicar. El ciclo completo está escrito y probado contra sustitutos del verify
de Keelokit: el logbook, las cuentas y los workers, los sellos, los convoys de `new` a `sail`, la
guardia del harbormaster y la importación única de un `BOARD.md` existente. Todavía no corrió en un
proyecto real. Lo diseñado y no escrito está al principio de [`docs/design.md`](docs/design.md).

## Comandos

| Comando | Qué hace |
|---|---|
| `/harbor:adopt` | Configura la política de convoys, la cuenta y la máquina de este clon, el logbook, el tope de la cuenta y los hotspots. Importa una vez un `BOARD.md` si lo hay |
| `/harbor:convoy new\|add\|status` | Abre un convoy, suma un vessel sellado, muestra qué se movió |
| `/harbor:convoy assemble\|verify\|sail` | Une `main` y los vessels en `convoy/<n>`; el ok y su nivel; un verify sobre la cabeza exacta; un push a `main` |
| `/harbor:convoy abort\|defer` | Abandona un convoy, o saca una historia atrasada para que el resto no espere |
| `/harbor:log` | El logbook: guardia, convoys, workers, cuentas |
| `/harbor:harbormaster takeover\|control` | Toma la guardia; la ronda que la renueva, registra cada movimiento de `main` y dice qué espera cada convoy |

## Probarlo

Necesita Keelokit 0.12.0 o posterior en el proyecto (`.keelokit/`), Python 3.11+, git y un remoto `origin`. Todavía no
está publicado. Para cargarlo desde un clon:

```bash
claude --plugin-dir /ruta/a/keelokit-harbor
```

Después corré `/harbor:adopt` en un proyecto con Keelokit. Tests: `python3 -m unittest discover -s tests`.

## Para tener en cuenta

- Harbor depende de Keelokit y no copia nada de su código. Corre el `pnpm verify` de Keelokit, lee
  su `state.toml` y usa sus niveles y su trailer `Story:`. Sin `.keelokit/`, Harbor imprime una
  línea y no hace nada.
- El hook de SessionStart corre `bin/harbor.py check` desde el plugin y lee `.keelokit/state.toml`
  y `.keelokit/local.toml` del proyecto. Funciona sin red y nunca bloquea una sesión.
- `harbor.py seal` corre el comando de `[harbor] vessel_verify` del `state.toml` del proyecto. Es
  código del proyecto, igual que sus tests.
- Un convoy con una historia de nivel full o que toca un área crítica también espera tu sí antes
  de zarpar: corrés `convoy approve <n>` en tu propia terminal. Un hook PreToolUse impide que lo
  corra un agente; como el guard de Keelokit, es un freno, no un sandbox
  (`[harbor] person_ok` = `critical`, `always` o `never`).
- Harbor empuja a `harbor/log` y a `convoy/<n>`, y a `main` solo en `convoy sail`: un fast-forward a
  una cabeza con sello verde y el ok del harbormaster. Nunca con `--force`.

## Licencia

Todavía no hay archivo de licencia: es decisión del autor.
