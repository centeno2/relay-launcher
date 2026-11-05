# Desarrollo

- `main`: versión revisada.
- `develop`: integración del siguiente cambio.
- `feature/<nombre>` y `fix/<nombre>`: trabajo de cada mejora o corrección;
  pull request hacia `develop`, y de `develop` hacia `main` para publicar.

```bash
git switch develop
git switch -c feature/mi-mejora
./desarrollo.sh
```

En Windows usa `iniciar.cmd`. El paquete conserva el nombre `bo2launcher`
para no romper los comandos existentes.

Instala `requirements.txt` en un entorno virtual y ejecuta:

```bash
python -m unittest discover -s tests -v
```

Las pruebas Qt usan el modo `offscreen`; las pruebas de procesos y descargas
utilizan dobles de prueba. No requieren el juego, Wine ni una cuenta online.
La [plantilla de GitHub Actions](docs/ci/tests.yml) cubre Linux y Windows con Python 3.12 y 3.14.
Las pruebas específicas de Wine/Niri solo se ejecutan en Linux.

La automatización está pendiente de activar: las credenciales utilizadas para
publicar no tienen permiso `workflow`. Con una credencial que lo permita,
copia `docs/ci/tests.yml` a `.github/workflows/tests.yml` y súbelo para ejecutar
la matriz. Publicar el código no implica que esa matriz ya haya pasado.

Antes de publicar, prueba el juego en un equipo real de cada plataforma.
No añadas archivos del juego, prefijos Wine, binarios descargados, registros
ni configuraciones de cuenta al repositorio.

Identidad visual: [design.md](docs/design.md).
