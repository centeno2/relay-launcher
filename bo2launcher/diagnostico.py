"""Diagnóstico local sin extraer archivos de sesión o contraseñas."""
import re
import sys
from . import backend as b


def redact(text: str) -> str:
    """Enmascara datos comunes por si el proveedor los imprimió en stdout."""
    text = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+", r"\1[OCULTO]", text)
    text = re.sub(r"(?i)(\b(?:access_token|refresh_token|password|passwd|secret|api_key)\s*[:=]\s*['\"]?)\S+", r"\1[OCULTO]", text)
    return re.sub(r"(?i)([?&](?:token|key|password|secret)=)[^&\s]+", r"\1[OCULTO]", text)


def main():
    print("=== BO2 Launcher 0.11 · Diagnóstico local ===")
    game = b.find_game()
    checks = (
        ("Archivos de BO2", game, game is not None),
        ("Wine privado", b.wine_path(), b.wine_path() is not None),
        ("Prefijo Wine", b.PREFIX, (b.PREFIX / "system.reg").exists()),
        ("DXVK", b.CONFIG / f"dxvk-{b.DXVK_VER}.installed", (b.CONFIG / f"dxvk-{b.DXVK_VER}.installed").exists()),
        ("Actualizador", b.PLUTONIUM, b.PLUTONIUM.is_file()),
        ("Motor T6 (LAN)", b.bootstrapper_path(), b.bootstrapper_path() is not None),
        ("Cliente oficial (online)", b.official_game_launcher_path(), b.official_game_launcher_path() is not None),
    )
    for title, path, ok in checks:
        print(f"{'OK' if ok else 'FALTA':5} {title}: {path or '(no encontrado)'}")
    print(f"Motor BO2 Zombies (Wine): {'DETECTADO' if b.game_process_alive() else 'NO DETECTADO'}")
    print(f"Consola T6 (Niri): {'DETECTADA' if b.game_console_visible() else 'NO DETECTADA'}")
    print(f"Config(s) de sesión: {len(b.account_session_paths())} (presencia NO significa sesión válida; no se leen tokens)")
    if game:
        statuses = {
            'sincronizado': 'OK · t6Path corresponde a la carpeta seleccionada',
            'pendiente-ruta': 'PENDIENTE · se puede corregir desde BO2 Launcher',
            'pendiente-cliente': 'PENDIENTE · instalar/iniciar primero el cliente oficial',
            'configuracion-invalida': 'REVISAR · config.json no es compatible o no se pudo leer',
            'configuracion-insegura': 'REVISAR · configuración enlazada',
        }
        try:
            status = b.official_game_path_status(game)
            print('Ruta del cliente online: ' + statuses.get(status, status))
        except RuntimeError as exc:
            print('Ruta del cliente online: REVISAR · ' + str(exc))
    print("Inicio online: URI oficial plutonium://play/t6zm; requiere cuenta autenticada y juego configurado")
    if "--red" in sys.argv:
        print("\n=== Comprobación de conectividad ===")
        b.check_connections(print)
    if "--sin-logs" not in sys.argv:
        for log in ("game.log", "updater.log", "plutonium.log"):
            fp = b.STATE / log
            print(f"\n=== Últimas 30 líneas de {fp} ===")
            if fp.is_file():
                try:
                    for line in fp.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]:
                        print(redact(line))
                except OSError as exc:
                    print(f"No se pudo leer el registro: {exc}")
            else:
                print("(sin registro)")
    print("\nNo se leen archivos de cuenta ni sesiones; revisa el texto antes de compartirlo.")


if __name__ == "__main__":
    main()
