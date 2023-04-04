import asyncio
import csv
import datetime
import io
import json
from os import environ
from pathlib import Path
from typing import Any, Callable

import discord
import httpx
from discord import Member, VoiceChannel
from dotenv import load_dotenv
from fastapi import FastAPI
from loguru import logger
from sentence_transformers import SentenceTransformer, util  # type: ignore

from pydantic import BaseModel

load_dotenv()

POSTING_CHANNEL_ID: str = environ["POSTING_CHANNEL_ID"]
DISCORD_API_TOKEN: str = environ["DISCORD_API_TOKEN"]
DISCORD_GUILD_ID: str = environ["DISCORD_GUILD_ID"]

SENTENCE_TRANSFORMER = SentenceTransformer("sentence-transformers/all-mpnet-base-v2")

DATA_DIR = Path("data")
RESOURCES_FILE = DATA_DIR / "resources.json"
SHIPS_FILE = DATA_DIR / "ships.csv"
LOCATIONS_FILE = DATA_DIR / "locations.json"

with open(RESOURCES_FILE) as f:
    RESOURCES = json.load(f)
with open(SHIPS_FILE) as f:
    SHIPS = list(csv.DictReader(f))
with open(LOCATIONS_FILE) as f:
    LOCATIONS = json.load(f)

DISCORD_MESSAGE_START = ""
DISCORD_API_ENDPOINT = "https://discordapp.com/api"
DISCORD_HEADERS = {
    "Authorization": f"Bot {DISCORD_API_TOKEN}",
    "Content-Type": "application/json",
}
DISCORD_CHANNEL_ENDPOINT = f"{DISCORD_API_ENDPOINT}/channels/{POSTING_CHANNEL_ID}"
DISCORD_MESSAGE_ENDPOINT = f"{DISCORD_CHANNEL_ENDPOINT}/messages"


class DiscordData(BaseModel):
    crew: list
    routes: list
    target_ships: list
    target_names: list
    booty: list
    last_hit: list


# DISCORD
intents = discord.Intents.default()
intents.members = True
discord_client = discord.Client(intents=intents)


@discord_client.event
async def on_ready() -> None:
    logger.info(f'Discord logged in as "{discord_client.user}"')


# FastAPI
app = FastAPI(title="Star Citizen Assisted Piracy API")


def find_best_route(booty: list[dict]) -> list:
    """Here be dragons"""
    sell_locations: dict = {}
    for b in booty:
        logger.info(b)
        for s in b["resource"]["sell"]:
            profit = s["price"] / b["resource"]["sell"][0]["price"]
            if profit > 0.9:
                if s["location"] not in sell_locations:
                    sell_locations[s["location"]] = []

                sell_locations[s["location"]].append(
                    b["resource"]["name"]
                    if profit == 1
                    else f'{b["resource"]["name"]} ({profit * 100:0.02}%)'
                )

    sell_locations_sorted = sorted(
        [([k], v) for k, v in sell_locations.items()],
        key=lambda s: len(s[1]),
        reverse=True,
    )

    result = []
    while sell_locations_sorted:
        tmp_sell_location, tmp_sell_resources = sell_locations_sorted.pop(0)

        if tmp_sell_resources:
            for r in tmp_sell_resources:
                for i, (sell_locations_l, sell_locations_r) in enumerate(
                    sell_locations_sorted
                ):
                    if tmp_sell_resources == sell_locations_r:
                        tmp_sell_location += sell_locations_l
                    if r in sell_locations_sorted[i][1]:
                        sell_locations_sorted[i][1].remove(r)

            result.append((tmp_sell_location, tmp_sell_resources))

    return result


@app.on_event("startup")
async def startup_event() -> None:
    asyncio.create_task(discord_client.start(DISCORD_API_TOKEN))


@app.get("/current_crew")
async def current_crew() -> list[dict]:
    return [
        {"nick": member.nick, "id": str(member.id)}
        for channel in discord_client.guilds[0].channels
        if isinstance(channel, VoiceChannel)
        for member in channel.members
    ]


def _search(collection: list, search_str: str, to_str: Callable[[Any], str]) -> Any:
    search_str_embedding = SENTENCE_TRANSFORMER.encode(
        search_str, convert_to_tensor=True
    )

    closest = 0
    for m in collection:
        if (
            similarity := util.pytorch_cos_sim(
                SENTENCE_TRANSFORMER.encode(to_str(m), convert_to_tensor=True),
                search_str_embedding,
            )
        ) > closest:
            closest = similarity
            document = m

    return document


@app.get("/search/members/{search_str}")
def search_members(search_str: str) -> dict:
    document = _search(
        [m for m in discord_client.guilds[0].members if not m.bot],
        search_str,
        lambda x: str(x.nick),
    )

    return {"nick": document.nick, "id": str(document.id)}


@app.get("/search/resources/{search_str}")
def search_resources(search_str: str) -> dict:
    return dict(_search(RESOURCES, search_str, lambda x: str(x["name"])))


@app.get("/search/ships/{search_str}")
def search_ships(search_str: str) -> dict:
    return dict(_search(SHIPS, search_str, lambda x: str(x["Name"])))


@app.get("/search/locations/{search_str}")
def search_locations(search_str: str) -> dict:
    return dict(_search(LOCATIONS, search_str, lambda x: str(x["name"])))


@app.post("/discord")
def post_to_discord(body: DiscordData) -> None:
    body.routes = sorted(body.routes, key=lambda r: str(r["name"]))
    body.target_ships = sorted(body.target_ships, key=lambda s: str(s["Name"]))
    body.target_names = sorted(body.target_names)
    body.crew = sorted(body.crew, key=lambda c: str(c["nick"]))
    body.last_hit = sorted(body.last_hit, key=lambda l: str(l["nick"]))
    body.booty = sorted(body.booty, key=lambda b: str(b["resource"]["name"]))

    fields = [
        {
            "name": "Route",
            "value": ", ".join(r["name"] for r in body.routes),
            "inline": True,
        },
        {
            "name": "Target",
            "value": ", ".join(s["Name"] for s in body.target_ships)
            + (
                ("\n" + f"({', '.join(body.target_names)})")
                if body.target_names
                else ""
            ),
            "inline": True,
        },
        {
            "name": "Crew",
            "value": ", ".join(f"<@{c['id']}>" for c in body.crew),
            "inline": False,
        },
    ]
    if body.last_hit:
        fields += [
            {
                "name": "Last Hit",
                "value": ", ".join(f"<@{c['id']}>" for c in body.last_hit),
                "inline": False,
            }
        ]

    if body.booty:
        sell_locations = find_best_route(body.booty)
        logger.debug(sell_locations)
        sell_strs = []
        for locations, location_resources in sell_locations:
            sell_strs.append(
                ", ".join(location_resources) + ":\n - " + "\n - ".join(locations)
            )

        fields += [
            {
                "name": "Booty",
                "value": "\n".join(
                    f'{b["amount"]} SCU of {b["resource"]["name"]}' for b in body.booty
                )
                + "\n----------------\n"
                + f"{sum(b['amount'] * b['resource']['sell'][0]['price'] for b in body.booty)} aUEC",
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

    # if body.screenshot_url"]:
    #     json_msg["embeds"][0]["thumbnail"] = {"url": body.screenshot_url"]}

    with open("test.json", "w") as f:
        json.dump(json_msg, f)

    httpx.post(DISCORD_MESSAGE_ENDPOINT, headers=DISCORD_HEADERS, json=json_msg)
