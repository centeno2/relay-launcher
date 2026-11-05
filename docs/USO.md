# Usar Relay

## Antes de empezar

- Python **3.12 o posterior**, con `pip` y `venv`, y Git.
- Linux x86_64 con escritorio gráfico, controladores Vulkan y las bibliotecas
  gráficas de Qt. Si faltan redistribuibles del juego, instala `winetricks` y
  `cabextract` con el gestor de paquetes de tu distribución y pulsa **Librerías Windows**.
- Windows **10/11 x64**, Python de [python.org](https://www.python.org/downloads/windows/)
  y los [requisitos de Plutonium](https://plutonium.pw/docs/system-requirements/).
- Conexión para el primer inicio, la descarga de componentes y el modo online.

`iniciar.sh` / `iniciar.cmd` crean `.venv` dentro del proyecto. Los siguientes
inicios reutilizan ese entorno. Si cambia `requirements.txt`, se actualiza.
En Windows también puedes abrir `iniciar.cmd` con doble clic.

## Juego y cuenta

Descarga y extrae el juego desde la
[carpeta compartida en Drive](https://drive.google.com/drive/folders/18CGqf5rwuULAL8-2XiH8-4UcGoKRUyNa?usp=sharing)
o selecciona tu instalación de Steam. El enlace de Drive es el compartido por
el mantenedor; sus permisos y disponibilidad dependen de Google Drive.

Selecciona la carpeta que contiene `zone/` y los datos de Zombies, no el ZIP
ni la carpeta que contiene todas tus bibliotecas. Relay también busca las
bibliotecas registradas de Steam.

En **Configuración**, instala los componentes y actualízalos. En
**Cuenta de Plutonium**, abre la sesión oficial para autenticarte la primera
vez. Cierra esa ventana y pulsa **Jugar Zombies**. Relay sincroniza la ruta
del juego con Plutonium y conserva una copia de la configuración anterior.
Consulta también la [guía oficial de instalación](https://plutonium.pw/docs/install/).

**LAN / sin conexión** inicia el motor local; necesita los componentes ya
instalados y no permite entrar a servidores públicos. El nombre de jugador
configurado en Relay se utiliza en este modo.

**Servidores** consulta GameServe.rs. La acción de jugar copia `connect IP:puerto`
al portapapeles e inicia Zombies: pega ese comando en la consola del juego.

## Escritorio y datos

**Sistema** sigue la paleta que Qt recibe del escritorio. **Claro** y **Oscuro**
son opciones manuales persistentes. Se mantienen las decoraciones de ventana
y la fuente del sistema. `Ctrl+,` abre Configuración; `Esc` vuelve a Jugar.
Puedes cambiar tanto la portada como el fondo desde Configuración.

| Datos | Linux | Windows |
| --- | --- | --- |
| Componentes de Relay | `$XDG_DATA_HOME/bo2-zombies-linux` | `%LOCALAPPDATA%\Relay` |
| Configuración | `$XDG_CONFIG_HOME/bo2-zombies-linux` | `%APPDATA%\Relay` |
| Registros | `$XDG_STATE_HOME/bo2-zombies-linux` | `%LOCALAPPDATA%\Relay\logs` |
| Cliente Plutonium | Dentro del prefijo Wine privado | `%LOCALAPPDATA%\Plutonium` |

Sin variables XDG, se usan `~/.local/share`, `~/.config` y `~/.local/state`.
Las carpetas Linux conservan el nombre anterior para reutilizar la instalación.

`./instalar.sh` añade Relay al menú de Linux y crea `relay-launcher` en
`~/.local/bin`. También conserva los comandos `bo2-launcher` y `bo2-diagnostico`.
Para otra ubicación: `./instalar.sh --prefix /ruta/absoluta` instala en
`bin/` y `share/` dentro de esa ruta.
La integración que oculta la consola es opcional y solo aparece en Niri.
Las actualizaciones usan Xvfb si está instalado; en otro caso muestran la
ventana normal del actualizador.

## Si algo falla

- **No abre la interfaz:** comprueba Python, `venv` y las dependencias Qt de tu
  distribución. En Linux, una sesión Wayland con problemas puede probar
  `QT_QPA_PLATFORM=xcb ./iniciar.sh` si tiene XWayland disponible.
- **Falta el motor:** pulsa **Actualizar componentes** y revisa **Actividad**.
- **Cuenta caducada / error 401:** cierra el juego y Plutonium; en **Cuenta de
  Plutonium** usa **Reparar error 401**. Se guarda un respaldo de la sesión.
- **Diagnóstico:** ejecuta `.venv/bin/python -m bo2launcher.diagnostico --red`
  en Linux o `.venv\Scripts\python -m bo2launcher.diagnostico --red` en Windows.

La interfaz y las rutas de Windows tienen pruebas automatizadas. El arranque
real del juego, los redistribuibles, los controladores y la autenticación
requieren validación en el equipo donde se juega.
