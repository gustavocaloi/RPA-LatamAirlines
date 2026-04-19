from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


LATAM_URL = "https://www.latamairlines.com/br/pt"
ROOT_DIR = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = ROOT_DIR / "artifacts"
PROFILE_DIR = ROOT_DIR / ".playwright-profile"


def log(message: str) -> None:
    print(f"[latam] {message}")


def first_visible(locators: Iterable[Locator], timeout_ms: int = 2500) -> Locator | None:
    for locator in locators:
        candidate = locator.first
        try:
            candidate.wait_for(state="visible", timeout=timeout_ms)
            return candidate
        except PlaywrightTimeoutError:
            continue
    return None


def access_denied(page: Page) -> bool:
    body_text = page.locator("body").inner_text(timeout=10_000)
    return "access denied" in body_text.lower() or "por razões de segurança" in body_text.lower()


def dismiss_cookie_banner(page: Page) -> None:
    buttons = [
        page.get_by_role("button", name=re.compile(r"aceitar|continuar|entendi|ok", re.I)),
        page.locator("[aria-label*='cookie' i] button"),
        page.locator("#onetrust-accept-btn-handler"),
    ]
    target = first_visible(buttons, timeout_ms=1200)
    if not target:
        return

    log("Fechando banner de cookies")
    target.click()


def open_origin_picker(page: Page) -> None:
    candidates = [
        page.get_by_label(re.compile(r"^(de|origem|saindo de|from)$", re.I)),
        page.get_by_role("combobox", name=re.compile(r"de|origem|from", re.I)),
        page.get_by_role("button", name=re.compile(r"de|origem|from", re.I)),
        page.locator("input[placeholder*='de' i]"),
        page.locator("input[placeholder*='origem' i]"),
        page.locator("[aria-label*='de' i]"),
        page.locator("[aria-label*='origem' i]"),
        page.locator("[data-testid*='origin' i]"),
        page.locator("[data-test*='origin' i]"),
    ]
    target = first_visible(candidates, timeout_ms=3000)
    if not target:
        raise RuntimeError("Nao encontrei o campo de origem na pagina da LATAM.")

    log("Abrindo seletor do campo De")
    target.click()


def fill_origin(page: Page, airport_code: str) -> None:
    airport_code = airport_code.strip().upper()
    open_origin_picker(page)

    input_candidates = [
        page.get_by_role("combobox"),
        page.locator("input[placeholder*='cidade' i]"),
        page.locator("input[placeholder*='origem' i]"),
        page.locator("input[placeholder*='de' i]"),
        page.locator("input[type='search']"),
        page.locator("dialog input"),
        page.locator("[role='dialog'] input"),
    ]
    active_input = first_visible(input_candidates, timeout_ms=2500)

    if active_input:
        active_input.click()
        active_input.press("Meta+A")
        active_input.fill(airport_code)
    else:
        page.keyboard.press("Meta+A")
        page.keyboard.type(airport_code, delay=100)

    log(f"Preenchendo origem com {airport_code}")

    option_candidates = [
        page.get_by_role("option", name=re.compile(rf"\\b{re.escape(airport_code)}\\b", re.I)),
        page.get_by_role("button", name=re.compile(rf"\\b{re.escape(airport_code)}\\b", re.I)),
        page.locator(f"text=/\\b{re.escape(airport_code)}\\b/i"),
    ]
    chosen_option = first_visible(option_candidates, timeout_ms=5000)

    if chosen_option:
        chosen_option.click()
    else:
        log("Nao encontrei sugestao explicita; usando teclado para confirmar")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")

    confirm_candidates = [
        page.locator(f"text=/\\b{re.escape(airport_code)}\\b/i"),
        page.locator(f"input[value*='{airport_code}']"),
        page.locator(f"[aria-label*='{airport_code}']"),
    ]
    if not first_visible(confirm_candidates, timeout_ms=5000):
        raise RuntimeError(f"O valor {airport_code} nao apareceu como selecionado apos o preenchimento.")


def run(from_airport: str, headless: bool, keep_open: bool) -> None:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    PROFILE_DIR.mkdir(exist_ok=True)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=headless,
            ignore_default_args=["--enable-automation"],
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": 1440, "height": 960},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            ),
        )
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4] });
            """
        )

        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(15_000)

        log(f"Abrindo {LATAM_URL}")
        page.goto(LATAM_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(4_000)

        if access_denied(page):
            page.screenshot(path=str(ARTIFACTS_DIR / "access-denied.png"), full_page=True)
            raise RuntimeError(
                "A LATAM bloqueou o acesso automatizado nesta execucao. "
                "Tente novamente em modo visivel, na sua rede habitual, ou reutilizando um perfil ja autenticado."
            )

        dismiss_cookie_banner(page)
        fill_origin(page, from_airport)
        page.screenshot(path=str(ARTIFACTS_DIR / "latam-preenchido.png"), full_page=True)
        log("Campo De preenchido com sucesso")

        if keep_open:
            log("Janela mantida aberta. Pressione Ctrl+C no terminal quando terminar.")
            try:
                page.wait_for_timeout(300_000)
            except KeyboardInterrupt:
                log("Encerrando por solicitacao do usuario")

        context.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Abre a LATAM Brasil e preenche o campo De com o codigo informado."
    )
    parser.add_argument("--from-airport", default="SJP", help="Codigo IATA da origem. Padrao: SJP.")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Executa sem abrir a janela do navegador.",
    )
    parser.add_argument(
        "--close",
        action="store_true",
        help="Fecha o navegador automaticamente apos preencher o campo.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        run(from_airport=args.from_airport, headless=args.headless, keep_open=not args.close)
        return 0
    except KeyboardInterrupt:
        log("Execucao interrompida")
        return 130
    except Exception as exc:
        log(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
