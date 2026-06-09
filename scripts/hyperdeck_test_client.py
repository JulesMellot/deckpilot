from __future__ import annotations

import argparse
import re
import socket
import time


BATCH_COMMANDS = [
    'device info',
    'configuration',
    'clips get',
    'slot info',
    'slot select: slot id: 1',
    'remote info',
    'preview info',
    'notify: transport: true slot: true clips: true',
    'transport info',
    'play',
    'playrange clear',
    'stop',
    'quit',
]


class HyperDeckTestClient:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.selected_clip_id: int | None = None
        self.last_clip_count = 0

    def connect(self) -> str:
        self.sock = socket.create_connection((self.host, self.port), timeout=3)
        greeting = self.recv_block(timeout=2.0)
        return greeting or '[pas de message de bienvenue recu]'

    def close(self) -> None:
        if self.sock is None:
            return
        try:
            self.sock.close()
        finally:
            self.sock = None

    def recv_block(self, timeout: float = 1.5) -> str:
        if self.sock is None:
            raise RuntimeError('Socket non connectee')

        deadline = time.monotonic() + timeout
        self.sock.settimeout(0.2)
        chunks: list[str] = []

        while time.monotonic() < deadline:
            try:
                data = self.sock.recv(4096)
            except socket.timeout:
                continue
            if not data:
                break
            chunks.append(data.decode('utf-8', errors='ignore'))
            if chunks[-1].endswith('\r\n\r\n'):
                break

        return ''.join(chunks).strip()

    def send_command(self, command: str, timeout: float = 1.5) -> str:
        if self.sock is None:
            raise RuntimeError('Socket non connectee')

        self.sock.sendall((command + '\r\n').encode('utf-8'))
        reply = self.recv_block(timeout=timeout)
        self._remember_state(command, reply)
        return reply

    def print_reply(self, command: str, reply: str, timeout: float) -> None:
        print(f'\n>> {command}')
        if reply:
            print(reply)
            return
        print(f'[aucune reponse recue en {timeout:.1f}s]')

    def run_command(self, command: str, timeout: float = 1.5) -> str:
        reply = self.send_command(command, timeout=timeout)
        self.print_reply(command, reply, timeout)
        return reply

    def run_sequence(self, title: str, items: list[tuple[str, float]]) -> None:
        print(f'\n=== {title} ===')
        for command, timeout in items:
            self.run_command(command, timeout=timeout)
            time.sleep(0.15)

    def run_batch(self) -> None:
        for command in BATCH_COMMANDS:
            timeout = 4.0 if command.startswith(('goto', 'play')) else 1.5
            self.run_command(command, timeout=timeout)
            time.sleep(0.25)

    def interactive_menu(self) -> None:
        while True:
            self._print_menu()
            choice = input('\nChoix: ').strip().lower()

            if choice == '1':
                self.run_sequence(
                    'Infos deck',
                    [
                        ('device info', 1.5),
                        ('configuration', 1.5),
                        ('slot info', 1.5),
                        ('remote info', 1.5),
                        ('preview info', 1.5),
                        ('transport info', 1.5),
                    ],
                )
            elif choice == '2':
                self.run_command('clips get', timeout=2.0)
            elif choice == '3':
                self._select_clip()
            elif choice == '4':
                clip_id = self._require_selected_clip()
                if clip_id is None:
                    continue
                self.run_command(f'goto: clip id: {clip_id}', timeout=4.0)
                self.run_command('transport info', timeout=1.5)
            elif choice == '5':
                self.run_sequence(
                    'Lecture clip deja charge',
                    [
                        ('play', 4.0),
                        ('transport info', 1.5),
                    ],
                )
            elif choice == '6':
                clip_id = self._require_selected_clip()
                if clip_id is None:
                    continue
                self.run_sequence(
                    'Lecture clip unique',
                    [
                        (f'playrange set: clip id: {clip_id}', 4.0),
                        ('play: single clip: true', 4.0),
                        ('transport info', 1.5),
                    ],
                )
            elif choice == '7':
                self.run_command('stop', timeout=2.0)
                self.run_command('transport info', timeout=1.5)
            elif choice == '8':
                self.run_sequence(
                    'Test connexion ATEM / HyperDeck',
                    [
                        ('device info', 1.5),
                        ('slot select: slot id: 1', 1.5),
                        ('remote: enable: true', 1.5),
                        ('notify: transport: true slot: true clips: true', 1.5),
                        ('remote info', 1.5),
                        ('transport info', 1.5),
                    ],
                )
            elif choice == '9':
                self.run_sequence(
                    'Test lecture video ATEM / HDMI',
                    [
                        ('slot select: slot id: 1', 1.5),
                        ('remote: enable: true', 1.5),
                        ('play', 4.0),
                        ('transport info', 1.5),
                        ('preview info', 1.5),
                    ],
                )
                print(
                    '\nIndice: si le transport passe a "play" avec le clip deja charge, '
                    'la chaine de controle reseau fonctionne. '
                    "La presence d'un signal HDMI reel reste a verifier sur l'ATEM."
                )
            elif choice == '10':
                self._test_exit_input_stops_playback()
            elif choice == '11':
                self._toggle_preview()
            elif choice == '12':
                self._toggle_remote()
            elif choice == '13':
                self.run_command('transport info', timeout=1.5)
            elif choice == '14':
                self._free_command()
            elif choice in {'15', 'q', 'quit', 'exit'}:
                self.run_command('quit', timeout=1.0)
                break
            else:
                print('Choix invalide.')

    def _print_menu(self) -> None:
        print('\n' + '=' * 60)
        print(f'HyperDeck test menu - {self.host}:{self.port}')
        print(f'Clip selectionne: {self.selected_clip_id if self.selected_clip_id is not None else "aucun"}')
        print('=' * 60)
        print('1. Voir les infos deck')
        print('2. Lister les clips')
        print('3. Choisir un clip')
        print('4. Preparer le clip choisi (goto)')
        print('5. Lancer le clip deja charge')
        print('6. Lancer le clip choisi en single clip')
        print('7. Stop')
        print('8. Tester la connexion ATEM / HyperDeck')
        print('9. Tester la lecture video ATEM / HDMI sur le clip charge')
        print("10. Tester si sortir de l'entree HyperDeck stoppe la lecture")
        print('11. Basculer preview on/off')
        print('12. Basculer remote on/off')
        print('13. Voir transport info')
        print('14. Envoyer une commande libre')
        print('15. Quitter')

    def _select_clip(self) -> None:
        reply = self.run_command('clips get', timeout=2.0)
        if not reply:
            print('Impossible de recuperer la liste des clips.')
            return

        default_value = '' if self.selected_clip_id is None else str(self.selected_clip_id)
        selected = input(f'Numero du clip [{default_value}]: ').strip()
        if not selected:
            return
        try:
            clip_id = int(selected)
        except ValueError:
            print('Numero invalide.')
            return
        if clip_id < 1:
            print('Le numero doit etre superieur a 0.')
            return
        self.selected_clip_id = clip_id
        print(f'Clip selectionne: {self.selected_clip_id}')

    def _toggle_preview(self) -> None:
        enabled = self._read_enabled_flag('preview info')
        target = not enabled if enabled is not None else True
        self.run_command(f'preview: enable: {str(target).lower()}', timeout=1.5)
        self.run_command('preview info', timeout=1.5)

    def _toggle_remote(self) -> None:
        enabled = self._read_enabled_flag('remote info')
        target = not enabled if enabled is not None else True
        self.run_command(f'remote: enable: {str(target).lower()}', timeout=1.5)
        self.run_command('remote info', timeout=1.5)

    def _test_exit_input_stops_playback(self) -> None:
        self.run_sequence(
            "Test sortie de l'entree HyperDeck",
            [
                ('slot select: slot id: 1', 1.5),
                ('remote: enable: true', 1.5),
                ('play', 4.0),
                ('transport info', 1.5),
            ],
        )

        print(
            "\nAction attendue: passe maintenant l'ATEM sur une autre entree "
            "que l'HyperDeck, puis reviens ici pour verifier l'etat du lecteur."
        )
        wait_input = input('Temps d attente en secondes avant verification [5]: ').strip()
        try:
            wait_seconds = float(wait_input) if wait_input else 5.0
        except ValueError:
            print('Valeur invalide, attente de 5 secondes.')
            wait_seconds = 5.0

        if wait_seconds > 0:
            print(f'Attente de {wait_seconds:.1f}s...')
            time.sleep(wait_seconds)

        reply = self.run_command('transport info', timeout=1.5)
        status = self._read_transport_status(reply)
        if status == 'stopped':
            print(
                "\nResultat: la lecture semble s'etre arretee apres la sortie "
                "de l'entree HyperDeck."
            )
        elif status == 'play':
            print(
                "\nResultat: la lecture continue. Sortir de l'entree HyperDeck "
                "ne stoppe pas automatiquement la lecture dans la configuration actuelle."
            )
        else:
            print(
                "\nResultat: impossible de determiner clairement l'etat du transport. "
                "Verifie aussi visuellement l'ATEM et la sortie video."
            )

    def _free_command(self) -> None:
        command = input('Commande HyperDeck: ').strip()
        if not command:
            print('Aucune commande envoyee.')
            return
        timeout_input = input('Timeout en secondes [2.0]: ').strip()
        try:
            timeout = float(timeout_input) if timeout_input else 2.0
        except ValueError:
            print('Timeout invalide, utilisation de 2.0s.')
            timeout = 2.0
        self.run_command(command, timeout=timeout)

    def _read_enabled_flag(self, info_command: str) -> bool | None:
        reply = self.send_command(info_command, timeout=1.5)
        self.print_reply(info_command, reply, 1.5)
        match = re.search(r'enabled:\s*(true|false)', reply, flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1).lower() == 'true'

    def _read_transport_status(self, reply: str) -> str | None:
        match = re.search(r'status:\s*([a-z]+)', reply, flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1).lower()

    def _require_selected_clip(self) -> int | None:
        if self.selected_clip_id is not None:
            return self.selected_clip_id
        print('Aucun clip choisi dans le CLI. Utilise d abord l option 3.')
        return None

    def _remember_state(self, command: str, reply: str) -> None:
        if command != 'clips get' or not reply:
            return
        clip_ids = [int(match.group(1)) for match in re.finditer(r'^\s*(\d+):', reply, flags=re.MULTILINE)]
        if not clip_ids:
            return
        self.last_clip_count = len(clip_ids)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Client de test HyperDeck interactif pour DeckPilot.',
    )
    parser.add_argument('host', nargs='?', default='127.0.0.1', help='IP ou hostname cible')
    parser.add_argument('port', nargs='?', type=int, default=9993, help='Port TCP cible')
    parser.add_argument(
        '--batch',
        action='store_true',
        help='Rejoue l ancienne sequence automatique au lieu d ouvrir le menu.',
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = HyperDeckTestClient(args.host, args.port)

    try:
        greeting = client.connect()
        print('CONNECTED TO', args.host, args.port)
        print(greeting)
        if args.batch:
            client.run_batch()
        else:
            client.interactive_menu()
    except KeyboardInterrupt:
        print('\nInterruption utilisateur.')
    finally:
        client.close()


if __name__ == '__main__':
    main()
