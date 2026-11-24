# Harbor

**Un plugin de Claude Code para subir muchas sesiones en paralelo a `main` en un solo convoy.**

*[Keelokit](https://github.com/leosimini/keelokit) · [Read in English](README.md)*

Escribí Harbor después de una semana subiendo sesiones en paralelo a mano en un monorepo real
hecho con [Keelokit](https://github.com/leosimini/keelokit). El tablero se separó de la realidad,
el «verde» de una rama dejó de corresponder a su último commit y hubo que renombrar timestamps de
migraciones al integrar. Harbor mantiene ese proceso y saca el trabajo manual. Sale de cientos de horas corriendo muchos proyectos en paralelo, muchas sesiones en varias
cuentas, entregando software las 24 horas con una intervención mínima. Lo mantengo como
hobby, al lado de Keelokit; es opinado y está hecho a mi manera de trabajar, así que tomá lo que te
sirva.

## La idea

Keelokit construye una historia por sesión y la sube a `main`. Con muchas sesiones, en más de una
cuenta de Claude o en más de una máquina, eso es un verify completo por subida, y nadie ve la
combinación hasta que ya está en `main`. Harbor las agrupa: cada sesión termina en su rama (un
*vessel*), un *skipper* integra el lote en `convoy/<n>`, se verifica una vez y, con el ok del
*harbormaster*, entra a `main` con un solo push. Las reglas importantes están escritas como
controles, no dejadas a la memoria:

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

## Qué hace

| Comando | Qué pasa |
|---|---|
| `/harbor:adopt` | Configura la política de convoys, la cuenta y la máquina de este clon, el logbook, el tope de la cuenta y los hotspots. Importa una vez un tablero llevado a mano si lo hay |
| `/harbor:convoy new\|add\|status` | Abre un convoy, suma un vessel sellado, muestra qué se movió |
| `/harbor:convoy assemble\|verify\|sail` | Une `main` y los vessels en `convoy/<n>`; el ok y su nivel; un verify sobre la cabeza exacta; un push a `main` |
| `/harbor:convoy abort\|defer` | Abandona un convoy, o saca una historia atrasada para que el resto no espere |
| `/harbor:log` | El logbook: guardia, convoys, workers, cuentas |
| `/harbor:harbormaster takeover\|control` | Toma la guardia; la ronda que la renueva, registra cada movimiento de `main` y dice qué espera cada convoy |
| `/harbor:dispatch` | Corre el despachante de una cuenta: entrega sus mensajes, lanza las sesiones que le pidieron y mantiene armado el vigía |
| `harbor.py msg send\|list\|ack\|done\|status\|watch` | Mensajes entre sesiones de cualquier cuenta, y al gatekeeper; acuses, atrasados y escalados; el vigía |
| `harbor.py wanted add\|take\|prompt\|started\|drop\|list` | Pedidos de sesiones nuevas, que hace el harbormaster y toma un despachante con lugar |
| `harbor.py title --role R [--convoy N] [--story ID] [--account A]` | El título que lleva una sesión: rol, cuenta, proyecto y alcance |
| `harbor.py account set A --mailbox-pr N` | Registra el buzón de la cuenta, el pull request borrador `harbor/mailbox/A` |
| `harbor.py push-guard LOCAL_REF LOCAL_SHA REMOTE_REF REMOTE_SHA` | Para el pre-push propio de un proyecto: sale con 0 si el push del cuaderno o de un buzón es válido, con 1 si no, con 3 si la ref no es de Harbor |
| `harbor.py doctor [--account A]` | Revisa esta máquina contra los `[harbor.requirements]` del proyecto: una línea por ítem, sale con 1 si falta alguno y con 2 si la revisión no pudo correr |

Sus hooks mantienen al día lo que cada sesión ve del logbook, para que no decida con un estado
viejo. Una sesión arranca con un fetch, ve qué cambió en el logbook en cada prompt y después de las
herramientas, y recibe los convoys abiertos antes de subir a `main`. Los detalles están en
[`docs/design.md`](docs/design.md#fresh-reads).

## Orquestación desde la nube

Las sesiones de una misma cuenta de Claude pueden lanzarse y mandarse mensajes entre sí; las de cuentas
distintas, no. Harbor 0.3 cierra ese hueco sin un servidor: el logbook lleva los mensajes y los pedidos de
sesiones nuevas, y cada cuenta corre una sesión **despachante** (`/harbor:dispatch`) que convierte lo que el
logbook tiene para su cuenta en acciones dentro de esa cuenta.

- **Mensajes entre cualquier sesión, de cualquier cuenta.** `harbor.py msg send --to <destino> TEXTO`, donde
  el destino es una cuenta, un worker, el `harbormaster`, el `skipper:<n>` de un convoy o el `gatekeeper`.
  Un mensaje queda en cola hasta que la cuenta que lo recibe lo acusa, así que un contenedor muerto nunca
  pierde uno.
- **Sesiones a pedido.** El harbormaster pide un vessel, un skipper o un despachante con
  `harbor.py wanted add`; el despachante de una cuenta con lugar lo toma (gana el primer commit) y lo lanza
  con un prompt que arma Harbor a partir del pedido, nunca de texto libre.
- **Un despertar que no cuesta nada.** El despachante deja corriendo `harbor.py msg watch` en segundo plano:
  shell, sin modelo, un fetch del logbook cada 30 s. Termina cuando hay trabajo, y al terminar despierta a
  la sesión. Medido: 13 s desde el mensaje de otra cuenta hasta que el despachante actúa.
- **Capas para cuando eso falla.** Nada garantiza que el contenedor de una sesión quieta siga vivo. Un
  mensaje está *atrasado* a los 15 minutos sin acuse o cuando su cuenta no tiene un vigía vivo; un latido
  programado por cuenta retoma al despachante cada pocas horas; las preguntas atrasadas, y cualquier
  mensaje con 30 minutos de atraso, van a la lista del gatekeeper. Detalle:
  [`docs/design.md`](docs/design.md#wakes-and-what-happens-when-one-fails).

Para armarlo, corré `/harbor:dispatch` una vez en una sesión de cada cuenta que deba recibir trabajo, y
seguí lo que dice sobre el latido.

## Títulos de sesión

Una cuenta puede tener muchas sesiones, y una lista de ellas tiene que decir cuál es cuál. Toda sesión que
Harbor conoce tiene un título que sale de `harbor.py title`, nunca escrito a mano, y se lee primero el rol,
después la cuenta y después el proyecto y el alcance: `harbormaster · acme-a · Acme`, `dispatcher · acme-a ·
Acme`, `skipper C8 · acme-a · Acme`, `vessel C8 · acme-a · Acme · wave 1 · STORY-001`, `worker · acme-a ·
Acme`. Cuando la guardia cambia de manos, al titular anterior se le indica que lleve `ex-harbormaster · …`
hasta que termine. El logbook lista las sesiones cuenta por cuenta, con sus títulos.

## Qué necesita una cuenta para trabajar acá

Lo que lleva el repositorio (`.claude/`, los lockfiles) llega a todas las cuentas por `main`. Lo que es de
una cuenta (su entorno en la nube, conectores, plugins, nombres de secretos) nunca viaja por git. Un proyecto
declara lo que su trabajo necesita:

```toml
[harbor.requirements]
tools = ["docker", "pnpm"]
hosts = ["registry.example.com"]
secrets = ["EXAMPLE_API_TOKEN"]       # solo nombres, nunca valores; variables de entorno
network_secrets = ["api.example.com"] # claves que una sesión en la nube inyecta en el proxy: "can't check"
plugins = ["design"]
skills = ["code-review"]
note = "una línea para el gatekeeper"
```

`harbor.py doctor` revisa la máquina contra eso y guarda el resultado por cuenta; cada despachante lo corre al
armarse y cada vez que la lista cambia, y manda lo que falte al gatekeeper, que decide qué configurar. Una
sesión en curso se entera, en el resumen del hook, cuando `main` cambió la lista, `.claude/` o un lockfile:
reinstalar después del próximo merge de `main` (un skipper lo toma en `convoy assemble`; una pieza entregada no mueve su rama); no se repite mientras el conjunto de cambios sea el mismo. El buzón de la cuenta, un pull request borrador llamado
`harbor/mailbox/<cuenta>` al que se suscribe su despachante, se registra con `account set --mailbox-pr N` (`0` lo olvida).

## El gatekeeper

Harbor lo operan personas, y en cada proyecto una tiene la última palabra: el **gatekeeper**, el humano que
opera la flota. Harbor lo conoce solo como un rol y nunca supone quién es. El gatekeeper da el sí que espera
un convoy (`convoy approve`, en su propia terminal; `[harbor] gatekeeper_ok` dice cuándo), responde las
preguntas que las sesiones mandan a `gatekeeper`, y se entera cuando un mensaje está tan atrasado que hace
falta una persona. Los agentes deciden dentro de lo que el gatekeeper ya decidió, y preguntan el resto.

## Probarlo

Necesitás Python 3.11+, git y un remoto `origin`; la capa de convoyes necesita además Keelokit 0.12.0 o
posterior en el proyecto (`.keelokit/`).

```bash
claude plugin marketplace add leosimini/keelokit-harbor
claude plugin install harbor@keelokit-harbor
```

O [descargá `harbor-plugin.zip`](https://github.com/leosimini/keelokit-harbor/releases/latest/download/harbor-plugin.zip)
y subilo en Claude (*Customize → Plugins → Upload*). Todas las versiones están en
[releases](https://github.com/leosimini/keelokit-harbor/releases). Para cargarlo desde un clon:
`claude --plugin-dir /ruta/a/keelokit-harbor`.

Después corré `/harbor:adopt` en un proyecto (con o sin Keelokit). Tests: `python3 -m unittest discover -s tests`. Lo
diseñado y no escrito está al principio de [`docs/design.md`](docs/design.md).

## Harbor sin Keelokit

La capa de flota no requiere Keelokit: los mensajes entre cuentas, los pedidos de sesión, el despachador, los
títulos, `doctor`, la guardia y los hooks funcionan en cualquier repositorio git con remoto. La configuración del
proyecto va en `.harbor/config.toml` (versionado) y la cuenta y el equipo de cada clon en `.harbor/local.toml`
(ignorado por git); `/harbor:adopt` escribe los dos. Los convoyes, los sellos y la importación del tablero
necesitan la política de convoyes de Keelokit (`/keelokit:project-adopt`) y lo dicen si se los pide sin ella. Un
proyecto con su propio hook de pre-push deja pasar las escrituras de Harbor con `push-guard`:

```bash
H=$(git config harbor.py)  # each session records the plugin's current harbor.py here
while read l ls r rs; do
  python3 "$H" push-guard "$l" "$ls" "$r" "$rs"; c=$?
  case $c in 0) continue;; 3) ;; *) exit 1;; esac  # 3: not Harbor's ref, the project's own rules go here
done
```

## Bueno saber

- Harbor no copia nada del código de Keelokit. Con Keelokit corre su `pnpm verify`, lee su `state.toml` y usa
  sus niveles y su trailer `Story:`. Cuando el ledger de Keelokit responde `ledger.py --json` con schema 1, el
  merge de cada vessel en un convoy lleva `Convoy: <n>`, y `convoy add` le pide a `ledger.py attribution` los
  commits del vessel: rechaza uno con un commit sin atribuir (`NO_STORY`) y toma la historia del vessel del
  ledger. Keelokit 0.16.0 todavía no responde `attribution`: hasta que lo haga, `convoy add` lo dice y lee los
  trailers `Story:`, como 0.5. Tomar una historia es un candado en la bitácora (`story take`, `worker register
  --story`): un segundo worker recibe `STORY_TAKEN` con quien la tiene, una historia que el ledger ve en el trunk
  `STORY_ON_TRUNK`, y el prompt de un vessel empieza con `ledger.py take <ID>`. Sin ese ledger, Harbor se comporta como 0.5. Sin `.keelokit/`, la capa de flota corre desde `.harbor/` (ver «Harbor sin
  Keelokit») y un repositorio sin ninguno de los dos directorios se deja en paz, sin decir nada.
- Los hooks corren `lib/harbor.py sync --hook` desde el plugin y leen la configuración y la identidad del
  proyecto (`.keelokit/state.toml` y `.keelokit/local.toml`, o `.harbor/config.toml` y `.harbor/local.toml`).
  Una sesión arranca con un fetch nuevo (tope de 4 s), ve qué cambió en el logbook en cada prompt (como máximo
  cada 60 s) y después de las herramientas (cada 2 min) y, con Keelokit, recibe los convoys abiertos antes de
  un push a `main`. Funcionan sin red y nunca bloquean una sesión.
- `harbor.py seal` corre el comando de `[harbor] vessel_verify` del `state.toml` del proyecto. Es
  código del proyecto, igual que sus tests.
- Un convoy con una historia de nivel full o que toca un área crítica también espera el sí del gatekeeper antes
  de zarpar: el gatekeeper corre `convoy approve <n>` en su propia terminal. Un hook PreToolUse impide que lo
  corra un agente; como el guard de Keelokit, es un freno, no un sandbox
  (`[harbor] gatekeeper_ok`, antes `person_ok`, = `critical`, `areas`, `always` o `never`; `areas` espera solo por un área crítica,
  no por el nivel full).
- Harbor empuja a `harbor/log` y a `convoy/<n>`, y a `main` solo en `convoy sail`: un fast-forward a
  una cabeza con sello verde y el ok del harbormaster. Nunca con `--force`.
- Si el verify del proyecto es un comando propio y no el `pnpm verify` de Keelokit (Keelokit adoptado
  en modo harness), poné `[harbor] own_verify = true` y tus comandos en `vessel_verify`,
  `convoy_verify` y `convoy_verify_all`. Harbor le da entonces su nivel a una corrida verde del
  convoy, así el convoy puede zarpar, y nunca escribe un sello compartido por ella: el pre-push de
  Keelokit, donde lo haya, sigue corriendo su propio verify.
- Donde esta página dice `main`, es el trunk: `[harbor] trunk` en `.keelokit/state.toml`, `main` por
  defecto. Si tu `main` es producción e integrás en `develop`, poné `trunk = "develop"`: los convoys
  se miden contra esa rama, la mergean y zarpan hacia ella, y Harbor nunca empuja a `main`.

## Cómo está hecho

[`docs/design.md`](docs/design.md) explica las piezas y los motivos. Harbor se prueba a sí mismo con
`python3 -m unittest discover -s tests`.

## Licencia

MIT — ver [LICENSE](LICENSE). Hecho por [Leopoldo Simini](https://leopoldosimini.com).
