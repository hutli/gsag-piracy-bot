import curses
import datetime
import io
import csv
import json
import time
from curses.textpad import Textbox, rectangle
from os import getenv
from pathlib import Path

import click
import click_pathlib
import dotenv
import editdistance
import httpx
from sentence_transformers import SentenceTransformer, util
from loguru import logger
from PIL import ImageGrab
from pynput import mouse

dotenv.load_dotenv()

INTERFACE_WIDTH = 90

MEMBERS_COLLECTION_NAME = "members_collection"
RESOURCE_COLLECTION_NAME = "resource_collection"
CONVERSATION_LOGGING_CHANNEL: int | None = (
    int(getenv("CONVERSATION_LOGGING_CHANNEL", 0) or 0) or None
)
DISCORD_API_TOKEN: str | None = getenv("DISCORD_API_TOKEN") or None
DISCORD_GUILD_ID: str | None = getenv("DISCORD_GUILD_ID") or None

DISCORD_API_ENDPOINT = "https://discordapp.com/api"
DISCORD_CHANNEL_ENDPOINT = (
    f"{DISCORD_API_ENDPOINT}/channels/{CONVERSATION_LOGGING_CHANNEL}"
)
DISCORD_MESSAGE_ENDPOINT = f"{DISCORD_CHANNEL_ENDPOINT}/messages"
DISCORD_HEADERS = {
    "Authorization": f"Bot {DISCORD_API_TOKEN}",
    "Content-Type": "application/json",
}
DISCORD_MESSAGE_START = ""
CONFIG_DIR = Path("config")
CONFIG_FILE = CONFIG_DIR / "config.json"

LOCATIONS_URL = "https://public.hutli.hu/sckl/config/locations.json"
RESOURCES_URL = "https://public.hutli.hu/sckl/config/resources.json"
SHIPS_URL = "https://public.hutli.hu/sckl/config/ships.csv"

INTRO = """Thank you for using the "GSAG Pirate Assist" command line tool!

If in doubt please visit https://github.com/hutli/gsag-pirate-assist.

                                  Lets get some booty! o7"""


def color_status(status: str) -> str:
    return f"""```ansi
{"[2;34m" if status.lower() == "operational" else "[2;31m"}{status}
[0m
```"""


def find_best_route(booty):
    """Here be dragons"""
    sell_locations = {}
    for b, _ in booty:
        for s in b["sell"]:
            if s not in sell_locations:
                sell_locations[s] = []

            sell_locations[s].append(b)

    sell_locations = sorted(
        [([k], v) for k, v in sell_locations.items()],
        key=lambda s: len(s[1]),
        reverse=True,
    )

    result = []
    while sell_locations:
        tmp_sell_location, tmp_sell_resources = sell_locations.pop(0)

        if tmp_sell_resources:
            for r in tmp_sell_resources:
                for i, (sell_locations_l, sell_locations_r) in enumerate(
                    sell_locations
                ):
                    if tmp_sell_resources == sell_locations_r:
                        tmp_sell_location += sell_locations_l
                    if r in sell_locations[i][1]:
                        sell_locations[i][1].remove(r)

            result.append((tmp_sell_location, tmp_sell_resources))

    return result


def post_to_discord(
    route: dict,
    target: str | None,
    ship: dict,
    booty: list,
    last_hit: dict | None,
    screenshot_url: str,
    config: dict,
) -> None:
    if DISCORD_API_TOKEN and CONVERSATION_LOGGING_CHANNEL:
        fields = [
            {
                "name": "Route",
                "value": route["name"],
                "inline": True,
            },
            {
                "name": "Target",
                "value": f"{ship['Name']}" + ("\n" + f"({target})" if target else ""),
                "inline": True,
            },
            {
                "name": "Crew",
                "value": ", ".join(
                    f'<@{c["user"]["id"]}>' for c in config["current_crew"]
                ),
                "inline": False,
            },
        ]
        if last_hit:
            fields += [
                {
                    "name": "Last Hit",
                    "value": f"<@{last_hit['user']['id']}>",
                    "inline": False,
                }
            ]

        if booty:
            sell_locations = find_best_route(booty)
            sell_strs = []
            for locations, location_resources in sell_locations:
                sell_strs.append(
                    ", ".join([r["name"] for r in location_resources])
                    + ":\n - "
                    + "\n - ".join(locations)
                )

            fields += [
                {
                    "name": "Booty",
                    "value": "\n".join(f'{a} SCU of {r["name"]}' for r, a in booty)
                    + "\n----------------\n"
                    + f"{sum(a * r['value'] for r,a in booty)} aUEC",
                    "inline": False,
                },
                {
                    "name": "Sell at",
                    "value": "\n\n".join(sell_strs),
                    "inline": False,
                },
            ]

        json_msg = {
            "content": DISCORD_MESSAGE_START,
            "tts": False,
            "embeds": [
                {
                    "type": "rich",
                    "title": f"Piracy achieved",
                    "description": "",
                    "color": 0xDC322F,
                    "fields": fields,
                    "timestamp": str(datetime.datetime.utcnow()),
                }
            ],
        }

        if screenshot_url:
            json_msg["embeds"][0]["thumbnail"] = {"url": screenshot_url}

        with open("test.json", "w") as f:
            json.dump(json_msg, f)

        return httpx.post(
            DISCORD_MESSAGE_ENDPOINT, headers=DISCORD_HEADERS, json=json_msg
        )


clicks = []


def on_click(x, y, button, pressed):
    global clicks
    if pressed:
        clicks.append((x, y))
        return False


def list_crew(crew):
    return "\n".join([f"{i}: {c['nick']}" for i, c in enumerate(crew)])


def construct_divider(text=None, symbol="="):
    final_header = f" {text} " if text else ""
    sides_len = int((INTERFACE_WIDTH - len(final_header)) / 2)
    final_text = symbol * sides_len + final_header + symbol * sides_len
    final_text += symbol * (INTERFACE_WIDTH - len(final_text))
    return final_text


def construct_line(text=""):
    return text + " " * (INTERFACE_WIDTH - len(text))


def central_msg(stdscr, text, symbol=" "):
    stdscr.addstr(4, 0, construct_line())
    stdscr.addstr(5, 0, construct_divider(text, symbol=symbol))
    stdscr.addstr(6, 0, construct_line())
    stdscr.refresh()


def ask_user(stdscr, header, input_name, pad=22):
    input_str = f"{input_name}:"
    input_str += " " * (pad - len(input_str))
    stdscr.addstr(4, 0, " " * len(input_str))
    stdscr.addstr(5, 0, input_str)
    stdscr.addstr(6, 0, " " * len(input_str))

    stdscr.addstr(3, 0, construct_divider(text=header, symbol="-"))
    editwin = curses.newwin(
        1, INTERFACE_WIDTH - 2 - len(input_str) - pad, 5, len(input_str) + 1
    )
    rectangle(stdscr, 4, len(input_str), 6, INTERFACE_WIDTH - 1 - pad)
    stdscr.refresh()

    box = Textbox(editwin)

    # Let the user edit until Ctrl-G is struck.
    box.edit()

    # Get resulting contents
    return box.gather().strip()


def ask_user_yn(stdscr, question, default=False):
    input_str = question + (" (y/N) " if not default else " (Y/n) ")

    central_msg(stdscr, input_str)

    resp = stdscr.getch()

    if resp == ord("y") or resp == ord("Y"):
        return True
    elif resp == ord("n") or resp == ord("N"):
        return False
    else:
        return default


SENTENCE_TRANSFORMER = SentenceTransformer("sentence-transformers/all-mpnet-base-v2")


def get_closest(stdscr, header, name, action, collection, key, default=False):
    document = None
    while not document:
        search_str = ask_user(stdscr, header, name)

        central_msg(stdscr, f'Searching for "{search_str}"...')

        search_str_embedding = SENTENCE_TRANSFORMER.encode(
            search_str, convert_to_tensor=True
        )

        closest = 0
        for m in collection:
            if (
                similarity := util.pytorch_cos_sim(
                    SENTENCE_TRANSFORMER.encode(m[key], convert_to_tensor=True),
                    search_str_embedding,
                )
            ) > closest:
                closest = similarity
                document = m

        if not ask_user_yn(stdscr, f'{action} "{document[key]}"?', default=default):
            document = None

    return document


def load_data():
    members = [
        m
        for m in httpx.get(
            f"{DISCORD_API_ENDPOINT}/guilds/{DISCORD_GUILD_ID}/members?limit=1000",
            headers=DISCORD_HEADERS,
        ).json()
        if m and ("bot" not in m["user"] or not m["user"]["bot"])
    ]

    resources = sorted(httpx.get(RESOURCES_URL).json(), key=lambda r: r["name"])

    ships = list(csv.DictReader(io.StringIO(httpx.get(SHIPS_URL).text)))

    locations = sorted(httpx.get(LOCATIONS_URL).json(), key=lambda l: l["name"])

    return members, resources, ships, locations


@click.command()
def cli():
    print()
    print(construct_divider("READ THIS"))
    print(INTRO)
    print(construct_divider("READ THIS"))
    if input("Understood? (y/N) ").lower() != "y":
        return

    CONFIG_DIR.mkdir(exist_ok=True, parents=True)

    members, resources, ships, locations = load_data()

    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()

    stdscr.addstr(0, 0, construct_divider("GSAG Pirate Assist"))
    stdscr.addstr(1, 0, construct_line())
    stdscr.addstr(2, 0, construct_line())
    stdscr.addstr(3, 0, construct_line())
    stdscr.addstr(4, 0, construct_line())
    stdscr.addstr(5, 0, construct_line())
    stdscr.addstr(6, 0, construct_line())
    stdscr.addstr(7, 0, construct_divider())

    if not CONFIG_FILE.exists():
        user = None
        while not user:
            user = get_closest(
                stdscr, "Who are you?", "Discord name", "Select", members, "nick"
            )

        with open(CONFIG_FILE, "w") as f:
            json.dump({"me": user, "current_crew": []}, f, indent=4)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    while True:
        members, resources, ships, locations = load_data()

        stdscr.clrtoeol()
        stdscr.refresh()
        stdscr.addstr(1, 0, construct_line(f"Welcome {config['me']['nick']}"))
        stdscr.addstr(
            2, 0, construct_line(f"Crew: {[c['nick'] for c in config['current_crew']]}")
        )
        stdscr.addstr(
            3, 0, construct_line(construct_divider(text="Main menu", symbol="-"))
        )
        stdscr.addstr(4, 0, construct_line("1. Update crew"))
        stdscr.addstr(5, 0, construct_line("2. Report piracy"))
        stdscr.addstr(6, 0, construct_line("q. Exit"))

        cmd = stdscr.getch()

        if cmd == ord("1"):
            stdscr.addstr(3, 0, construct_divider(text="Updating crew", symbol="-"))
            stdscr.addstr(4, 0, construct_line("1. Add crew"))
            stdscr.addstr(5, 0, construct_line("2. Remove crew"))
            stdscr.addstr(6, 0, construct_line("*. Back"))

            cmd = stdscr.getch()

            if cmd == ord("1"):
                document = get_closest(
                    stdscr, "Adding crew", "Name", "Add", members, "nick"
                )

                config["current_crew"] = sorted(
                    [*config["current_crew"], document], key=lambda y: y["nick"]
                )
            elif cmd == ord("2"):
                document = get_closest(
                    stdscr, "Removing crew", "Name", "Remove", members, "nick"
                )

                config["current_crew"] = [
                    c
                    for c in config["current_crew"]
                    if c["user"]["id"] != document["user"]["id"]
                ]

            with open(CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=4)

        elif cmd == ord("2"):
            stdscr.addstr(3, 0, construct_divider(text="Reporting", symbol="-"))
            stdscr.addstr(4, 0, construct_line())
            stdscr.addstr(5, 0, construct_divider("Screenshot? (y/N)", " "))
            stdscr.addstr(6, 0, construct_line())

            screenshot_url = None

            ans = stdscr.getch()
            if ans == ord("y") or ans == ord("Y"):
                stdscr.addstr(
                    3,
                    0,
                    construct_divider(text="Reporting - Taking screenshot", symbol="-"),
                )

                stdscr.addstr(5, 0, construct_divider("Please click top-left", " "))
                stdscr.refresh()
                listener = mouse.Listener(on_click=on_click)
                listener.start()
                listener.join()

                stdscr.addstr(6, 0, construct_divider("and bottom-right", " "))
                stdscr.refresh()
                listener = mouse.Listener(on_click=on_click)
                listener.start()
                listener.join()

                screenshot = ImageGrab.grab(
                    bbox=(clicks[0][0], clicks[0][1], clicks[1][0], clicks[1][1])
                )

                bio = io.BytesIO()
                screenshot.save(bio, format="PNG")  # Since there is no filename,
                # you need to be explicit about the format
                bio.seek(0)  # rewind the file we wrote into
                screenshot_filename = f"{time.time()}.png"
                httpx.put(
                    f"https://upload.hutli.hu/sc/{screenshot_filename}",
                    data=bio.getvalue(),
                )
                screenshot_url = f"https://public.hutli.hu/sc/{screenshot_filename}"

            intercept_location = get_closest(
                stdscr,
                "Reporting - Intercept location",
                "Location name",
                "Select",
                locations,
                "name",
            )

            player = None
            if ask_user_yn(stdscr, "Got player target name?", default=True):
                player = ask_user(stdscr, "Reporting - Target", "Username(s)")

            ship = get_closest(
                stdscr, "Reporting - Target", "Ship", "Select", ships, "Name"
            )

            booty = []
            while ask_user_yn(stdscr, "Got (more) booty?", default=True):
                resource = get_closest(
                    stdscr,
                    "Reporting - Booty",
                    "Resource name",
                    "Select",
                    resources,
                    "name",
                    default=True,
                )
                amount = int(
                    ask_user(stdscr, "Reporting - Booty", "Amount (in whole SCU)")
                )
                if amount:
                    booty.append((resource, amount))

            last_hit = None
            if ask_user_yn(stdscr, "Last hit?", default=False):
                last_hit = get_closest(
                    stdscr, "Reporting - Last hit", "Name", "Select", members, "nick"
                )

            central_msg(stdscr, "Posting...")
            r = post_to_discord(
                intercept_location,
                player,
                ship,
                booty,
                last_hit,
                screenshot_url,
                config,
            )
            if r.is_success:
                central_msg(stdscr, "Posted!")
                time.sleep(5)
            else:
                central_msg(
                    stdscr,
                    f"DISCORD HTTP ERROR | {r.status_code}: {r.text}",
                    symbol="!",
                )
                resp = stdscr.getch()

        elif cmd == ord("q") or cmd == ord("Q"):
            curses.echo()
            curses.nocbreak()
            curses.endwin()
            return


if __name__ == "__main__":
    cli()
