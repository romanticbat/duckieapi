from flask import Flask, send_file, request, make_response
from PIL import Image, ImageDraw, ImageFont, ImageSequence
from io import BytesIO
import os
import requests
import threading
import time

app = Flask(__name__)

# ================================================================
# FUNÇÕES DE SUPORTE
# ================================================================

def get_ema_image():
    local_path = os.path.join("images", "hud_battle.png")
    try:
        return Image.open(local_path).convert("RGBA")
    except Exception as e:
        print(f"Erro ao carregar hud_battle.png: {e}")
        return None


def get_background_image(filename=None):
    if filename:
        local_path = os.path.join("images", "backs", filename)
    else:
        local_path = os.path.join("images", "backs", "base.jpg")

    try:
        img = Image.open(local_path)
        if getattr(img, "is_animated", False):
            print(f"[INFO] Fundo animado detectado: {filename}")
        return img
    except Exception as e:
        print(f"Erro ao carregar background {local_path}: {e}")
        return Image.new("RGBA", (960, 480), (255, 255, 255, 255))


def resize_image(image, target_height=96):
    ratio = target_height / float(image.size[1])
    width = int(float(image.size[0]) * ratio)
    return image.resize((width, target_height), Image.BICUBIC)


def get_real_pokemon_name(pokemon_identifier):
    if str(pokemon_identifier).isdigit():
        url = f"https://pokeapi.co/api/v2/pokemon/{pokemon_identifier}"
        response = requests.get(url)
        if response.status_code == 200:
            name = response.json()["name"]
        else:
            name = str(pokemon_identifier)
    else:
        name = str(pokemon_identifier)

    name = name.lower().strip()

    form_map = {
        "-mega-x": "M.",
        "-mega-y": "M.",
        "-mega": "M.",
        "-alola": "A.",
        "-alolan": "A.",
        "-hisui": "H.",
        "-hisuian": "H.",
        "-galar": "G.",
        "-galarian": "G.",
        "-paldea": "P.",
        "-paldean": "P.",
    }

    for form_suffix, prefix in form_map.items():
        if form_suffix in name:
            base_name = name.replace(form_suffix, "")
            extra = ""
            if form_suffix.endswith("-x"):
                extra = " X"
            elif form_suffix.endswith("-y"):
                extra = " Y"
            return f"{prefix} {base_name.capitalize()}{extra}"

    return name.capitalize()


def get_pokemon_sprite(pokemon_name, is_pokemon1=False, shiny=False, target_height=96):
    if str(pokemon_name).isdigit():
        pokemon_id = int(pokemon_name)
        if pokemon_id >= 10000:
            side = "back" if is_pokemon1 else "front"
            shiny_tag = "s" if shiny else "n"
            filename = f"{pokemon_id}-{side}-{shiny_tag}.gif"
            local_path = os.path.join("msprites", filename)
            if os.path.exists(local_path):
                try:
                    sprite = Image.open(local_path)
                    return sprite
                except Exception as e:
                    print(f"Erro ao carregar sprite local ({filename}): {e}")

    url = f"https://pokeapi.co/api/v2/pokemon/{pokemon_name.lower()}"
    response = requests.get(url)
    if response.status_code != 200:
        return None

    data = response.json()
    if is_pokemon1:
        sprite_key = "back_shiny" if shiny else "back_default"
        fallback_key = "front_shiny" if shiny else "front_default"
    else:
        sprite_key = "front_shiny" if shiny else "front_default"
        fallback_key = None

    sprite_url = data.get("sprites", {}).get(sprite_key)
    if not sprite_url and fallback_key:
        sprite_url = data.get("sprites", {}).get(fallback_key)
    if not sprite_url:
        return None

    sprite_response = requests.get(sprite_url)
    if sprite_response.status_code == 200:
        sprite = Image.open(BytesIO(sprite_response.content)).convert("RGBA")
        return resize_image(sprite, target_height=target_height)
    return None


def get_hp_image(color):
    local_path = os.path.join("images", "bars", f"overlay_{color}.jpg")
    try:
        return Image.open(local_path).convert("RGBA")
    except Exception as e:
        print(f"Erro ao carregar {local_path}: {e}")
        return None


def choose_hp_color(hp_ratio):
    if hp_ratio > 0.5:
        return "green"
    elif hp_ratio > 0.2:
        return "orange"
    else:
        return "red"


def draw_hp_bar(battle_image, position, hp_ratio, bar_width=92, bar_height=4):
    color = choose_hp_color(hp_ratio)
    hp_img = get_hp_image(color)
    if not hp_img:
        return
    hp_ratio = max(0, min(1, hp_ratio))
    fill_width = int(bar_width * hp_ratio)
    hp_resized = hp_img.resize((bar_width, bar_height), Image.BICUBIC)
    cropped = hp_resized.crop((0, 0, fill_width, bar_height))
    battle_image.paste(cropped, position, cropped)


def _apply_effects(draw, battle_image):
    def paste_if_exists(filename, position, size, folder):
        if not filename:
            return
        path = os.path.join("images", folder, f"{filename}.png")
        if os.path.exists(path):
            try:
                effect = Image.open(path).convert("RGBA")
                effect = effect.resize((size, size), Image.BICUBIC)
                battle_image.paste(effect, position, effect)
            except Exception as e:
                print(f"Erro ao carregar {filename}: {e}")

    paste_if_exists(request.args.get("effect1"), (168, 132), 12, "effects")
    paste_if_exists(request.args.get("effect2"), (106, 22), 12, "effects")
    paste_if_exists(request.args.get("gender1"), (208, 116), 11, "icons")
    paste_if_exists(request.args.get("gender2"), (65, 24), 11, "icons")

    positions_p2 = [(2, 50)]
    positions_p1 = [(240, 152)]
    paste_if_exists(request.args.get("ball1"), positions_p1[0], 15, "icons")
    paste_if_exists(request.args.get("ball2"), positions_p2[0], 15, "icons")


def _draw_texts(draw, battle_image, pokemon1, pokemon2, font_scale):
    try:
        font = ImageFont.truetype("pokemon-ds-font.ttf", int(2.2 * font_scale))
        font_turn = ImageFont.truetype("pokemon-ds-font.ttf", int(2.6 * font_scale))
    except IOError:
        font = font_turn = ImageFont.load_default()

    battle_turn = request.args.get("turn", "1")
    draw.text((203, 133), f"{battle_turn}", fill=(40, 40, 40), font=font_turn)

    real_pokemon1 = get_real_pokemon_name(pokemon1)
    real_pokemon2 = get_real_pokemon_name(pokemon2)

    level1 = request.args.get("level1", "1")
    level2 = request.args.get("level2", "1")

    draw.text((5, 23), real_pokemon2, fill=(0, 0, 0), font=font)
    draw.text((93, 23), f"{level2}", fill=(0, 0, 0), font=font)

    bbox1 = draw.textbbox((0, 0), real_pokemon1, font=font)
    text_width1 = bbox1[2] - bbox1[0]
    x = 180 - text_width1 // 2
    draw.text((x, 115), real_pokemon1, fill=(0, 0, 0), font=font)
    draw.text((235, 115), f"{level1}", fill=(0, 0, 0), font=font)


# ================================================================
# GERAÇÃO DE IMAGEM/GIF
# ================================================================

def create_battle_image(pokemon1, pokemon2, sprite_height=96, hp_bar_scale=1.0, font_scale=5.0):
    shiny1 = request.args.get("shiny1", "false").lower() == "true"
    shiny2 = request.args.get("shiny2", "false").lower() == "true"
    background_name = request.args.get("back")
    background = get_background_image(background_name)
    ema_image = get_ema_image()

    sprite1 = get_pokemon_sprite(pokemon1, is_pokemon1=True, shiny=shiny1, target_height=sprite_height * 2)
    sprite2 = get_pokemon_sprite(pokemon2, is_pokemon1=False, shiny=shiny2, target_height=sprite_height * 2)

    if sprite1 is None or sprite2 is None:
        return None, "png"

    hp1 = float(request.args.get("hp1", 100))
    hp2 = float(request.args.get("hp2", 100))
    hp1_ratio = max(0, min(1, hp1 / 100))
    hp2_ratio = max(0, min(1, hp2 / 100))

    if getattr(background, "is_animated", False):
        background_frames = [f.convert("RGBA").copy() for f in ImageSequence.Iterator(background)]
    else:
        background_frames = [background.convert("RGBA")]

    if getattr(sprite1, "is_animated", False) or getattr(sprite2, "is_animated", False) or getattr(background, "is_animated", False):
        frames = []
        durations = []
        max_frames = max(len(background_frames), getattr(sprite1, "n_frames", 1), getattr(sprite2, "n_frames", 1))

        for i in range(max_frames):
            bg_frame = background_frames[i % len(background_frames)].copy()
            battle_frame = bg_frame.copy()

            if getattr(sprite1, "is_animated", False):
                frame1 = ImageSequence.Iterator(sprite1)[i % sprite1.n_frames].convert("RGBA")
                frame1 = resize_image(frame1, target_height=sprite_height * 2)
            else:
                frame1 = sprite1

            if getattr(sprite2, "is_animated", False):
                frame2 = ImageSequence.Iterator(sprite2)[i % sprite2.n_frames].convert("RGBA")
                frame2 = resize_image(frame2, target_height=sprite_height * 2)
            else:
                frame2 = sprite2

            battle_frame.paste(frame1, (20, 75), frame1)
            battle_frame.paste(frame2, (140, 10), frame2)

            draw_hp_bar(battle_frame, (70, 39), hp2_ratio)
            draw_hp_bar(battle_frame, (206, 130), hp1_ratio)

            if ema_image:
                battle_frame.paste(ema_image, (0, 0), ema_image)

            draw = ImageDraw.Draw(battle_frame)
            _apply_effects(draw, battle_frame)
            _draw_texts(draw, battle_frame, pokemon1, pokemon2, font_scale)

            frames.append(battle_frame)
            durations.append(80)

        output = BytesIO()
        frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:], loop=0, duration=durations, disposal=2)
        output.seek(0)
        return output, "gif"

    # imagem estática
    battle_image = background.convert("RGBA").copy()
    battle_image.paste(sprite1, (20, 75), sprite1)
    battle_image.paste(sprite2, (140, 10), sprite2)
    draw_hp_bar(battle_image, (70, 39), hp2_ratio)
    draw_hp_bar(battle_image, (206, 130), hp1_ratio)

    if ema_image:
        battle_image.paste(ema_image, (0, 0), ema_image)

    draw = ImageDraw.Draw(battle_image)
    _apply_effects(draw, battle_image)
    _draw_texts(draw, battle_image, pokemon1, pokemon2, font_scale)

    output = BytesIO()
    battle_image.save(output, format="PNG")
    output.seek(0)
    return output, "png"


# ================================================================
# ROTAS
# ================================================================

@app.route("/battle", methods=["GET"])
def battle():
    pokemon1 = request.args.get("pokemon1")
    pokemon2 = request.args.get("pokemon2")
    if not pokemon1 or not pokemon2:
        return "Please provide both pokemon1 and pokemon2 parameters.", 400

    sprite_height = int(request.args.get("sprite_height", 55))
    hp_bar_scale = float(request.args.get("hp_bar_scale", 1.5))
    font_scale = float(request.args.get("font_scale", 6.0))

    battle_image, img_type = create_battle_image(pokemon1, pokemon2, sprite_height, hp_bar_scale, font_scale)
    if battle_image is None:
        return "Failed to retrieve one or both Pokémon sprites.", 400

    mimetype = "image/gif" if img_type == "gif" else "image/png"
    return send_file(battle_image, mimetype=mimetype)


# ✅ ROTA COMPATÍVEL COM DISCORD
@app.route("/battle.gif", methods=["GET"])
def battle_gif():
    pokemon1 = request.args.get("pokemon1")
    pokemon2 = request.args.get("pokemon2")
    if not pokemon1 or not pokemon2:
        return "Please provide both pokemon1 and pokemon2 parameters.", 400

    sprite_height = int(request.args.get("sprite_height", 55))
    hp_bar_scale = float(request.args.get("hp_bar_scale", 1.5))
    font_scale = float(request.args.get("font_scale", 6.0))

    battle_image, img_type = create_battle_image(pokemon1, pokemon2, sprite_height, hp_bar_scale, font_scale)
    if battle_image is None:
        return "Failed to retrieve one or both Pokémon sprites.", 400

    response = make_response(battle_image.getvalue())
    if img_type == "gif":
        response.headers["Content-Type"] = "image/gif"
        filename = "battle.gif"
    else:
        response.headers["Content-Type"] = "image/png"
        filename = "battle.png"

    response.headers["Content-Disposition"] = f"inline; filename={filename}"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


# ================================================================
# AUTO PING
# ================================================================

def auto_ping():
    url = "https://duckieapi.onrender.com/battle.gif?pokemon1=4&pokemon2=1&hp1=80&hp2=65&level1=100&level2=100&shiny1=true&shiny2=true"
    while True:
        try:
            response = requests.get(url)
            now = time.strftime("%d/%m/%Y %H:%M:%S")
            print(f"[{now}] Ping enviado! Status code: {response.status_code}")
        except Exception as e:
            print(f"Erro ao enviar ping: {e}")
        time.sleep(300)


if __name__ == "__main__":
    threading.Thread(target=auto_ping, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=True)
