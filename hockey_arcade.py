"""
Hockey RPG - true arcade-style real-time version.
Control a skater (WASD/arrows), shoot with Space, play 3 periods against an AI team.
"""
import math
import random
import sys

import numpy as np
import pygame
import pygame.sndarray
from pygame.math import Vector2

WIDTH, HEIGHT = 900, 620
FPS = 60

# ---------- procedural audio synthesis ----------
# No recorded samples are bundled with the game; every sound effect and the
# music loop are generated at startup from raw waveforms via numpy, then
# converted into pygame.mixer.Sound objects. These three helpers are the
# shared building blocks every sound in `build_sound_bank` composes from.

AUDIO_SAMPLE_RATE = 44100


def _tone(freq, duration, sample_rate=AUDIO_SAMPLE_RATE, waveform="sine"):
    """A single-frequency waveform as a float array in [-1, 1]."""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    if waveform == "sine":
        return np.sin(2 * np.pi * freq * t)
    if waveform == "square":
        return np.sign(np.sin(2 * np.pi * freq * t))
    if waveform == "triangle":
        return 2 * np.abs(2 * ((t * freq) % 1) - 1) - 1
    raise ValueError(f"unknown waveform: {waveform}")


def _noise(duration, sample_rate=AUDIO_SAMPLE_RATE):
    """White noise as a float array in [-1, 1], for percussive/crowd sounds."""
    return np.random.uniform(-1.0, 1.0, int(sample_rate * duration))


def _envelope(wave, attack_sec=0.01, decay_rate=5.0, sample_rate=AUDIO_SAMPLE_RATE):
    """Apply a linear attack then an exponential decay across the whole wave."""
    n = len(wave)
    env = np.ones(n)
    attack_n = min(int(attack_sec * sample_rate), n)
    env[:attack_n] = np.linspace(0, 1, attack_n)
    decay_n = n - attack_n
    if decay_n > 0:
        env[attack_n:] = np.exp(-decay_rate * np.linspace(0, 1, decay_n))
    return wave * env


def _sustain_envelope(wave, attack_sec=0.02, release_sec=0.05, sample_rate=AUDIO_SAMPLE_RATE):
    """Linear attack, flat sustain, then linear release - for held tones like a
    whistle or horn, where _envelope's continuous exponential decay would fade
    the sound out almost immediately instead of holding it."""
    n = len(wave)
    env = np.ones(n)
    attack_n = min(int(attack_sec * sample_rate), n)
    release_n = min(int(release_sec * sample_rate), n - attack_n)
    env[:attack_n] = np.linspace(0, 1, attack_n)
    if release_n > 0:
        env[n - release_n:] = np.linspace(1, 0, release_n)
    return wave * env


def _to_sound(wave, volume=0.5):
    """Convert a float array in [-1, 1] into a stereo pygame.mixer.Sound."""
    wave = np.clip(wave, -1.0, 1.0)
    stereo = np.column_stack([wave, wave])
    pcm = (stereo * volume * 32767).astype(np.int16)
    return pygame.sndarray.make_sound(np.ascontiguousarray(pcm))


def build_sfx_bank():
    shoot_wave = _envelope(_noise(0.15), attack_sec=0.002, decay_rate=10)
    shoot = _to_sound(shoot_wave, volume=0.5)

    hit_wave = _tone(150, 0.1, waveform="square") + _noise(0.1)
    hit_wave = _envelope(hit_wave, attack_sec=0.002, decay_rate=14)
    hit = _to_sound(hit_wave, volume=0.5)

    check_wave = _tone(90, 0.22, waveform="square") + 0.4 * _noise(0.22)
    check_wave = _envelope(check_wave, attack_sec=0.002, decay_rate=9)
    check = _to_sound(check_wave, volume=0.65)

    whistle_wave = _tone(2800, 0.4)
    whistle_wave = _sustain_envelope(whistle_wave, attack_sec=0.02, release_sec=0.08)
    whistle = _to_sound(whistle_wave, volume=0.45)

    goal_horn_wave = _tone(220, 1.2, waveform="sine") + _tone(330, 1.2, waveform="sine")
    goal_horn_wave = _sustain_envelope(goal_horn_wave, attack_sec=0.05, release_sec=0.3)
    goal_horn = _to_sound(goal_horn_wave, volume=0.4)

    return {
        "shoot": shoot,
        "hit": hit,
        "check": check,
        "whistle": whistle,
        "goal_horn": goal_horn,
    }


def build_crowd_sounds():
    sample_rate = AUDIO_SAMPLE_RATE
    crowd_cheer_duration = 2.5
    crowd_ambience_duration = 2.0

    # crowd cheer: average several phase-shifted copies of one noise burst
    # together to dull the harsh white-noise edge into something closer to a
    # roar, then rise-and-fade it like a real crowd reaction to a goal
    noise = _noise(crowd_cheer_duration, sample_rate)
    shifted_noises = [noise]
    for i in range(1, 5):
        shifted_noises.append(np.roll(noise, i * int(sample_rate * 0.1), axis=0))
    smoothed_noise = np.mean(shifted_noises, axis=0)
    smoothed_noise = _sustain_envelope(smoothed_noise, attack_sec=0.5, release_sec=1.5)
    crowd_cheer = _to_sound(smoothed_noise, volume=0.5)

    # crowd ambience: same smoothing trick for a duller background murmur,
    # held flat (not decayed) so it loops seamlessly at a steady quiet level
    noise = _noise(crowd_ambience_duration, sample_rate)
    shifted_noises = [noise]
    for i in range(1, 3):
        shifted_noises.append(np.roll(noise, i * int(sample_rate * 0.1), axis=0))
    smoothed_noise = np.mean(shifted_noises, axis=0)
    smoothed_noise = _sustain_envelope(smoothed_noise, attack_sec=0.05, release_sec=0.05)
    crowd_ambience = _to_sound(smoothed_noise, volume=0.15)

    return {
        "crowd_cheer": crowd_cheer,
        "crowd_ambience": crowd_ambience,
    }


def build_music_loop():
    """A short ambient pad loop for the title/game-over screens, built from a
    four-chord progression (i-VI-III-VII in A minor) rather than a single
    drone, so it has some gentle harmonic movement."""
    sample_rate = AUDIO_SAMPLE_RATE
    chord_duration = 1.6
    progression = [
        (110.00, 130.81, 164.81),  # Am: A2, C3, E3
        (87.31, 110.00, 130.81),   # F:  F2, A2, C3
        (130.81, 164.81, 196.00),  # C:  C3, E3, G3
        (98.00, 123.47, 146.83),   # G:  G2, B2, D3
    ]
    chords = []
    for freqs in progression:
        chord = sum(_tone(f, chord_duration, waveform="triangle") for f in freqs) / len(freqs)
        chord = _envelope(chord, attack_sec=0.3, decay_rate=0.6)
        chords.append(chord)
    loop_wave = np.concatenate(chords)
    # fade the very tail to zero so looping doesn't click at the seam
    tail_n = int(0.15 * sample_rate)
    loop_wave[-tail_n:] *= np.linspace(1, 0, tail_n)
    return _to_sound(loop_wave, volume=0.22)


def build_sound_bank():
    sounds = {}
    sounds.update(build_sfx_bank())
    sounds.update(build_crowd_sounds())
    sounds["music"] = build_music_loop()
    return sounds

RINK_LEFT, RINK_RIGHT = 40, WIDTH - 40
RINK_TOP, RINK_BOTTOM = 90, HEIGHT - 40
GOAL_HEIGHT = 110
GOAL_DEPTH = 16

WHITE = (240, 240, 245)
BLACK = (10, 10, 14)
ICE = (205, 225, 245)
BOARD = (40, 50, 70)
RED = (210, 70, 70)
BLUE = (60, 120, 220)
GOLD = (220, 180, 60)
PUCK_COLOR = (20, 20, 20)
GOAL_COLOR = (180, 180, 190)

PERIOD_SECONDS = 60  # arcade-length period
PICKUP_RADIUS = 20
STEAL_RADIUS = 18
PUCK_COOLDOWN_FRAMES = 15
CHECK_RADIUS = 26
CHECK_COOLDOWN_FRAMES = 40
BATTLE_THRESHOLD = 8.0
GOAL_REPLAY_FRAMES = 90  # freeze/zoom celebration beat after a goal, before faceoff resets


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ---------- behind-the-player perspective camera ----------
# Gameplay/physics stay in flat top-down world coordinates (unchanged, tested).
# Only rendering projects that world through a chase camera positioned behind
# the user's skater, looking the direction they're facing - this is what turns
# the top-down sim into a 3rd-person "over the shoulder" view.

CAMERA_BACK_DIST = 60
CAMERA_SMOOTH = 0.12
HORIZON_Y = 150
FOCAL = 170
# calibrated so a point ~45 world-units ahead of the camera (near the puck/
# nearby players) lands at the bottom of the screen, and the projection
# approaches the horizon as depth grows - without this, near objects (like
# the puck right at your stick) project far below the visible screen.
NEAR_REF_DEPTH = 45
GROUND_DROP = (HEIGHT - HORIZON_Y) * NEAR_REF_DEPTH / FOCAL
LATERAL_MULT = 1.55
MIN_DEPTH = 18


class Camera:
    def __init__(self, pos, forward):
        self.pos = Vector2(pos)
        self.forward = Vector2(forward)
        if self.forward.length_squared() == 0:
            self.forward = Vector2(1, 0)
        self.forward = self.forward.normalize()

    def follow(self, target_pos, target_facing):
        desired_forward = Vector2(target_facing)
        if desired_forward.length_squared() == 0:
            desired_forward = self.forward
        else:
            desired_forward = desired_forward.normalize()
        self.forward = (self.forward * (1 - CAMERA_SMOOTH) + desired_forward * CAMERA_SMOOTH)
        if self.forward.length_squared() > 0:
            self.forward = self.forward.normalize()

        desired_pos = Vector2(target_pos) - self.forward * CAMERA_BACK_DIST
        self.pos = self.pos * (1 - CAMERA_SMOOTH) + desired_pos * CAMERA_SMOOTH

    def right(self):
        return Vector2(-self.forward.y, self.forward.x)

    def project(self, world_pos):
        """Returns (screen_x, screen_y, scale, depth) or None if behind the camera."""
        rel = Vector2(world_pos) - self.pos
        depth = rel.dot(self.forward)
        if depth < MIN_DEPTH:
            return None
        lateral = rel.dot(self.right())
        scale = clamp(FOCAL / depth, 0.0, 6.0)
        screen_x = WIDTH / 2 + lateral * scale * LATERAL_MULT
        screen_y = HORIZON_Y + GROUND_DROP * scale
        return screen_x, screen_y, scale, depth


class Puck:
    def __init__(self):
        self.pos = Vector2(WIDTH / 2, HEIGHT / 2)
        self.vel = Vector2(0, 0)
        self.radius = 7
        self.carrier = None
        self.cooldown = 0
        self.save_rolled = True  # becomes False once a shot is taken, until a goalie resolves it
        self.trail = [(self.pos.x, self.pos.y) for _ in range(6)]

    def update(self):
        if self.carrier:
            offset = self.carrier.facing * (self.carrier.radius + self.radius + 2)
            self.pos = self.carrier.pos + offset
            self.vel = Vector2(0, 0)
            self.trail.pop(0)
            self.trail.append((self.pos.x, self.pos.y))
            return None

        self.pos += self.vel
        self.vel *= 0.985
        if self.cooldown > 0:
            self.cooldown -= 1

        goal = None
        # top/bottom boards
        if self.pos.y - self.radius < RINK_TOP:
            self.pos.y = RINK_TOP + self.radius
            self.vel.y *= -0.8
        elif self.pos.y + self.radius > RINK_BOTTOM:
            self.pos.y = RINK_BOTTOM - self.radius
            self.vel.y *= -0.8

        goal_top = HEIGHT / 2 - GOAL_HEIGHT / 2
        goal_bottom = HEIGHT / 2 + GOAL_HEIGHT / 2
        in_goal_mouth = goal_top < self.pos.y < goal_bottom

        if self.pos.x - self.radius < RINK_LEFT:
            if in_goal_mouth:
                if self.pos.x < RINK_LEFT - GOAL_DEPTH:
                    goal = "right"  # right team scored on left net
            else:
                self.pos.x = RINK_LEFT + self.radius
                self.vel.x *= -0.8
        elif self.pos.x + self.radius > RINK_RIGHT:
            if in_goal_mouth:
                if self.pos.x > RINK_RIGHT + GOAL_DEPTH:
                    goal = "left"  # left team scored on right net
            else:
                self.pos.x = RINK_RIGHT - self.radius
                self.vel.x *= -0.8

        self.trail.pop(0)
        self.trail.append((self.pos.x, self.pos.y))
        return goal


class Skater:
    def __init__(self, team, x, y, color, speed, shot_power, steal, is_user=False, is_goalie=False, label=""):
        self.team = team  # "left" or "right"
        self.pos = Vector2(x, y)
        self.vel = Vector2(0, 0)
        self.facing = Vector2(1, 0) if team == "left" else Vector2(-1, 0)
        self.color = color
        self.speed = speed
        self.shot_power = shot_power
        self.steal = steal
        self.is_user = is_user
        self.is_goalie = is_goalie
        self.radius = 14 if not is_goalie else 17
        self.label = label
        self.shoot_cooldown = 0
        self.accel = self.speed * 0.35
        self.glide_friction = 0.90
        self.trail = []
        self.lean = 0.0  # signed turn sharpness, for visual lean
        self.jersey_number = random.randint(2, 97)
        self.stamina = 100.0
        self.sprinting = False
        self.deke_timer = 0
        self.deke_cooldown = 0
        self.stride_phase = random.uniform(0, 6.28)
        self.spray_trigger = False
        self.strafe_facing = None  # when set, facing is locked to this dir instead of following velocity
        self.stun_timer = 0
        self.check_cooldown = 0
        self.control_points = 0.0  # accumulator for contested puck battles

    def update_movement(self, move_vec, sprint=False, strafe_target=None):
        if self.check_cooldown > 0:
            self.check_cooldown -= 1
        if self.stun_timer > 0:
            self.stun_timer -= 1
            move_vec = Vector2(0, 0)  # knocked off balance - no steering until it wears off
            sprint = False

        effective_speed = self.speed * (1.35 if sprint and self.stamina > 0 else 1.0)
        base_accel = self.accel * (1.5 if sprint and self.stamina > 0 else 1.0)
        # real strides aren't a constant push: force pulses on push-off and drops during
        # the glide phase. Averages back to base_accel over a full cycle so overall pace
        # is unchanged, but moment-to-moment acceleration now surges and eases.
        push_pulse = 1.0 + 0.5 * math.sin(self.stride_phase)
        effective_accel = base_accel * push_pulse
        self.sprinting = sprint and self.stamina > 0 and move_vec.length_squared() > 0
        old_speed = self.vel.length()

        if move_vec.length_squared() > 0:
            target_dir = move_vec.normalize()
            cur_speed = self.vel.length()

            if cur_speed > 0.08 and self.deke_timer == 0:
                cur_dir = self.vel.normalize()
                angle_diff = cur_dir.angle_to(target_dir)
                if angle_diff > 180:
                    angle_diff -= 360
                elif angle_diff < -180:
                    angle_diff += 360
                # carving a turn: tighter at low speed (like digging an edge),
                # wider/slower at full speed (momentum resists instant direction change) -
                # mirrors a real skating crossover turn instead of snapping instantly.
                speed_ratio = cur_speed / self.speed if self.speed else 0
                max_turn_deg = max(4.0, 16.0 - speed_ratio * 11.0)
                clamped = clamp(angle_diff, -max_turn_deg, max_turn_deg)
                new_dir = cur_dir.rotate(clamped)
                self.lean = clamp(clamped / max_turn_deg, -1.0, 1.0) if max_turn_deg else 0.0
            else:
                # a deke bypasses the normal turn-rate limit: an instant sharp fake
                new_dir = target_dir
                self.lean = 0.0

            self.facing = Vector2(new_dir)
            new_speed = min(cur_speed + effective_accel, effective_speed)
            self.vel = new_dir * new_speed
        else:
            self.vel *= self.glide_friction
            if self.vel.length() < 0.05:
                self.vel = Vector2(0, 0)
            self.lean *= 0.8

        self.pos += self.vel
        self.stride_phase += 0.25 + self.vel.length() * 0.45

        # defensive strafing: lock facing toward a target (e.g. the puck) while still
        # moving freely in any direction - decouples "where you look" from "where you go".
        if strafe_target is not None:
            to_target = Vector2(strafe_target) - self.pos
            if to_target.length_squared() > 1:
                self.facing = to_target.normalize()

        new_speed_after = self.vel.length()
        self.spray_trigger = (
            not self.is_goalie
            and ((abs(self.lean) > 0.75 and new_speed_after > 0.8) or (old_speed - new_speed_after > 1.3))
        )

        self.trail.append(Vector2(self.pos))
        if len(self.trail) > 10:
            self.trail.pop(0)

        bounced = False
        if self.pos.x < RINK_LEFT + self.radius:
            self.pos.x = RINK_LEFT + self.radius
            bounced = True
        elif self.pos.x > RINK_RIGHT - self.radius:
            self.pos.x = RINK_RIGHT - self.radius
            bounced = True
        if self.pos.y < RINK_TOP + self.radius:
            self.pos.y = RINK_TOP + self.radius
            bounced = True
        elif self.pos.y > RINK_BOTTOM - self.radius:
            self.pos.y = RINK_BOTTOM - self.radius
            bounced = True
        if bounced:
            self.vel *= 0.3

        if self.shoot_cooldown > 0:
            self.shoot_cooldown -= 1
        if self.deke_timer > 0:
            self.deke_timer -= 1
        if self.deke_cooldown > 0:
            self.deke_cooldown -= 1

        if self.sprinting:
            self.stamina = max(0.0, self.stamina - 0.9)
        else:
            self.stamina = min(100.0, self.stamina + 0.4)

    def try_deke(self):
        """A quick fake: instant sharp turn + brief steal immunity. Costs stamina, has a cooldown."""
        if self.deke_cooldown > 0 or self.stamina < 18:
            return False
        self.deke_timer = 10
        self.deke_cooldown = 45
        self.stamina -= 18
        return True

    def goal_pos(self, attacking_goal_x):
        return Vector2(attacking_goal_x, HEIGHT / 2)


def make_teams(user_stats):
    left = []
    right = []

    user_speed = 2.2 + user_stats["skating"] * 0.12
    user_shot = 7 + user_stats["shooting"] * 0.5
    user_steal = 0.3 + user_stats["defense"] * 0.02

    user = Skater(
        "left", RINK_LEFT + 120, HEIGHT / 2, BLUE,
        speed=user_speed, shot_power=user_shot, steal=user_steal,
        is_user=True, label="YOU",
    )
    left.append(user)
    left.append(Skater("left", RINK_LEFT + 180, HEIGHT / 2 - 100, (90, 140, 230), speed=2.6, shot_power=7, steal=0.4, label="CPU"))
    left.append(Skater("left", RINK_LEFT + 180, HEIGHT / 2 + 100, (90, 140, 230), speed=2.6, shot_power=7, steal=0.4, label="CPU"))
    left.append(Skater("left", RINK_LEFT + 20, HEIGHT / 2, (40, 80, 170), speed=2.0, shot_power=0, steal=0.5, is_goalie=True, label="G"))

    right.append(Skater("right", RINK_RIGHT - 150, HEIGHT / 2, RED, speed=2.6, shot_power=7, steal=0.45, label="CPU"))
    right.append(Skater("right", RINK_RIGHT - 220, HEIGHT / 2 - 100, (230, 100, 100), speed=2.5, shot_power=6.5, steal=0.4, label="CPU"))
    right.append(Skater("right", RINK_RIGHT - 220, HEIGHT / 2 + 100, (230, 100, 100), speed=2.5, shot_power=6.5, steal=0.4, label="CPU"))
    right.append(Skater("right", RINK_RIGHT - 20, HEIGHT / 2, (170, 50, 50), speed=2.0, shot_power=0, steal=0.5, is_goalie=True, label="G"))

    return left, right


def ai_move_vector(skater, puck, all_skaters, own_goal_x, opp_goal_x):
    if skater.is_goalie:
        target_y = clamp(puck.pos.y, HEIGHT / 2 - GOAL_HEIGHT / 2 + 10, HEIGHT / 2 + GOAL_HEIGHT / 2 - 10)
        target = Vector2(own_goal_x + (14 if own_goal_x < WIDTH / 2 else -14), target_y)
        d = target - skater.pos
        return d if d.length_squared() > 4 else Vector2(0, 0)

    if puck.carrier is skater:
        target = Vector2(opp_goal_x, HEIGHT / 2)
        d = target - skater.pos
        return d
    if puck.carrier is not None and puck.carrier.team == skater.team:
        # support: move toward attacking zone, offset from puck carrier
        lane_y = HEIGHT / 2 + (100 if skater.pos.y < HEIGHT / 2 else -100)
        target = Vector2((skater.pos.x + opp_goal_x) / 2, lane_y)
        d = target - skater.pos
        return d
    # puck loose or held by opponent -> chase it
    d = puck.pos - skater.pos
    return d


def resolve_skater_collisions(all_skaters):
    n = len(all_skaters)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = all_skaters[i], all_skaters[j]
            delta = b.pos - a.pos
            dist = delta.length()
            min_dist = a.radius + b.radius
            if 0 < dist < min_dist:
                overlap = min_dist - dist
                push = delta.normalize() * (overlap / 2)
                a.pos -= push
                b.pos += push
            elif dist == 0:
                a.pos += Vector2(1, 0)


def resolve_puck_battle(contestants, puck):
    """A short tug-of-war for a loose puck contested by 2+ opposing skaters
    (board/net-front battles), instead of an instant first-to-arrive grab.
    Each contestant accumulates control points frame by frame from their
    steal stat plus a small luck factor; first to cross the threshold wins.
    Call this every frame the contest is active; returns the winner or None."""
    for skater in contestants:
        skater.control_points += skater.steal * 0.3 + random.random() * 0.15
        if skater.control_points >= BATTLE_THRESHOLD:
            for s in contestants:
                s.control_points = 0.0
            return skater
    return None


def resolve_check(attacker, defender, puck):
    """A body-check attempt: attacker tries to separate defender from the puck
    (or just knock them around) by skating into them. Costs attacker stamina
    either way; a whiffed check still costs a little for the attempt."""
    if attacker.check_cooldown > 0:
        return False
    attacker.check_cooldown = CHECK_COOLDOWN_FRAMES

    attacker_speed = attacker.vel.length()
    defender_speed = defender.vel.length()

    SPEED_MARGIN = 0.8
    has_closing_speed = attacker_speed - defender_speed >= SPEED_MARGIN
    has_stamina = attacker.stamina >= 15

    if has_closing_speed and has_stamina:
        attacker.stamina -= 15
        success = random.random() < 0.75
    else:
        attacker.stamina -= 4
        success = False

    if success:
        knockback_strength = min(2.0 + attacker_speed, 6.0)
    else:
        knockback_strength = 0.0

    if not success:
        return False

    away = defender.pos - attacker.pos
    if away.length_squared() < 1:
        away = Vector2(1, 0) if attacker.team == "left" else Vector2(-1, 0)
    away = away.normalize()
    defender.vel = away * knockback_strength
    defender.stun_timer = 30
    if puck.carrier is defender:
        puck.carrier = None
        puck.cooldown = PUCK_COOLDOWN_FRAMES
        puck.vel = away * (knockback_strength * 0.5)
    return True


def resolve_shoot(shooter, puck, opp_goal_x):
    # aimed shot: where you're facing when you shoot steers where it goes,
    # rewarding good positioning/timing instead of a pure random roll.
    goal_top = HEIGHT / 2 - GOAL_HEIGHT / 2 + 10
    goal_bottom = HEIGHT / 2 + GOAL_HEIGHT / 2 - 10
    aim_y = clamp(shooter.pos.y + shooter.facing.y * 150, goal_top, goal_bottom)
    aim_y += random.uniform(-12, 12)  # small imperfection so it isn't a laser
    target = Vector2(opp_goal_x, aim_y)
    direction = (target - shooter.pos)
    if direction.length_squared() == 0:
        direction = shooter.facing
    direction = direction.normalize()
    puck.carrier = None
    puck.vel = direction * shooter.shot_power
    puck.cooldown = PUCK_COOLDOWN_FRAMES
    puck.save_rolled = False
    shooter.shoot_cooldown = 25


class ArcadeGame:
    def __init__(self, user_stats=None):
        self.user_stats = user_stats or {"shooting": 5, "skating": 5, "defense": 5}
        pygame.init()
        pygame.mixer.init(frequency=AUDIO_SAMPLE_RATE, size=-16, channels=2, buffer=512)
        pygame.display.set_caption("Hockey RPG - Arcade")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 20)
        self.big_font = pygame.font.SysFont("consolas", 34, bold=True)
        self.small_font = pygame.font.SysFont("consolas", 13)

        self.sounds = build_sound_bank()
        self.music_channel = pygame.mixer.Channel(0)
        self.ambience_channel = pygame.mixer.Channel(1)

        self.start_new_game()
        self.enter_state("TITLE")

    def enter_state(self, new_state):
        self.state = new_state
        if new_state == "PLAYING":
            self.music_channel.stop()
            self.ambience_channel.play(self.sounds["crowd_ambience"], loops=-1)
        else:
            self.ambience_channel.stop()
            self.music_channel.play(self.sounds["music"], loops=-1)

    def start_new_game(self):
        self.left_team, self.right_team = make_teams(self.user_stats)
        self.all_skaters = self.left_team + self.right_team
        self.puck = Puck()
        user = self.user_skater()
        self.camera = Camera(user.pos - user.facing * CAMERA_BACK_DIST, user.facing)
        self.score = {"left": 0, "right": 0}
        self.period = 1
        self.time_left = PERIOD_SECONDS * FPS
        self.enter_state("PLAYING")
        self.message = ""
        self.message_timer = 0
        self.sprays = []
        self.hit_particles = []
        self.shake_timer = 0
        self.shake_strength = 0.0
        self.shake_offset = Vector2(0, 0)
        self.goal_replay_timer = 0
        self.goal_replay_team = None
        self.zoom_scale = 1.0

    def reset_positions(self, scorer_team):
        self.left_team, self.right_team = make_teams(self.user_stats)
        self.all_skaters = self.left_team + self.right_team
        self.puck = Puck()
        user = self.user_skater()
        self.camera = Camera(user.pos - user.facing * CAMERA_BACK_DIST, user.facing)
        self.sprays = []
        self.hit_particles = []
        self.shake_timer = 0
        self.shake_offset = Vector2(0, 0)
        self.goal_replay_timer = 0
        self.goal_replay_team = None
        self.zoom_scale = 1.0

    def spawn_spray(self, skater):
        for _ in range(5):
            jitter = Vector2(random.uniform(-1, 1), random.uniform(-1, 1))
            away = (-skater.vel) if skater.vel.length_squared() > 0.01 else jitter
            if away.length_squared() > 0:
                away = away.normalize()
            vel = away.rotate(random.uniform(-40, 40)) * random.uniform(0.6, 1.8)
            self.sprays.append({"pos": Vector2(skater.pos), "vel": vel, "life": random.randint(10, 18)})

    def update_sprays(self):
        for s in self.sprays:
            s["pos"] += s["vel"]
            s["vel"] *= 0.85
            s["life"] -= 1
        self.sprays = [s for s in self.sprays if s["life"] > 0]

    def spawn_hit_particles(self, pos):
        for _ in range(random.randint(10, 12)):
            jitter = Vector2(random.uniform(-1, 1), random.uniform(-1, 1))
            vel = jitter.rotate(random.uniform(0, 360)) * random.uniform(1.0, 2.5)
            self.hit_particles.append({"pos": Vector2(pos), "vel": vel, "life": random.randint(20, 30)})

    def update_hit_particles(self):
        for p in self.hit_particles:
            p["pos"] += p["vel"]
            p["vel"] *= 0.80
            p["life"] -= 1
        self.hit_particles = [p for p in self.hit_particles if p["life"] > 0]

    def update_shake(self):
        if self.shake_timer > 0:
            self.shake_timer -= 1
            self.shake_offset = Vector2(
                random.uniform(-1, 1), random.uniform(-1, 1)
            ) * self.shake_strength
        else:
            self.shake_offset = Vector2(0, 0)

    def shake_camera(self, strength, frames):
        self.shake_timer = frames
        self.shake_strength = strength

    def user_skater(self):
        return self.left_team[0]

    def step(self, dt_frames=1):
        """Advance the simulation by one tick. Returns True if a goal/period/game event happened."""
        if self.state != "PLAYING":
            return False

        if self.message_timer > 0:
            self.message_timer -= 1

        if self.goal_replay_timer > 0:
            self.goal_replay_timer -= 1
            # quick push-in over the first third of the window, then hold
            progress = 1.0 - (self.goal_replay_timer / GOAL_REPLAY_FRAMES)
            self.zoom_scale = 1.0 + 0.35 * min(progress * 3, 1.0)
            self.update_sprays()
            self.update_hit_particles()
            self.update_shake()
            if self.goal_replay_timer == 0:
                self.reset_positions(self.goal_replay_team)
                self.goal_replay_team = None
                self.zoom_scale = 1.0
            return True

        keys = pygame.key.get_pressed()
        move = Vector2(0, 0)
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            move.x -= 1
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            move.x += 1
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            move.y -= 1
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            move.y += 1

        sprint_held = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
        # defensive strafing: hold Ctrl to keep facing the puck while moving freely in
        # any direction - lets you shadow a puck carrier sideways without turning away.
        strafe_held = keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]
        user = self.user_skater()
        strafe_target = self.puck.pos if strafe_held else None
        user.update_movement(move, sprint=sprint_held, strafe_target=strafe_target)
        self.camera.follow(user.pos, user.facing)
        if user.spray_trigger:
            self.spawn_spray(user)

        for skater in self.all_skaters:
            if skater.is_user:
                continue
            own_goal_x = RINK_LEFT if skater.team == "left" else RINK_RIGHT
            opp_goal_x = RINK_RIGHT if skater.team == "left" else RINK_LEFT
            mv = ai_move_vector(skater, self.puck, self.all_skaters, own_goal_x, opp_goal_x)
            # defenders shadow the puck carrier sideways instead of turning to chase it head-on
            ai_strafe_target = (
                self.puck.pos
                if (not skater.is_goalie and self.puck.carrier is not None and self.puck.carrier.team != skater.team)
                else None
            )
            ai_sprint = (
                not skater.is_goalie
                and mv.length_squared() > 0
                and (self.puck.carrier is None or self.puck.carrier.team != skater.team)
                and random.random() < 0.4
            )
            skater.update_movement(mv, sprint=ai_sprint, strafe_target=ai_strafe_target)
            if skater.spray_trigger:
                self.spawn_spray(skater)

            if (
                not skater.is_goalie
                and skater.deke_cooldown == 0
                and self.puck.carrier is skater
                and random.random() < 0.01
            ):
                skater.try_deke()

            if (
                not skater.is_goalie
                and self.puck.carrier is skater
                and skater.shoot_cooldown == 0
                and abs(skater.pos.x - opp_goal_x) < 260
                and random.random() < 0.02
            ):
                resolve_shoot(skater, self.puck, opp_goal_x)
                self.sounds["shoot"].play()

            if (
                not skater.is_goalie
                and skater.check_cooldown == 0
                and self.puck.carrier is not None
                and self.puck.carrier.team != skater.team
                and random.random() < 0.015
            ):
                nearest_opp = min(
                    (s for s in self.all_skaters if s.team != skater.team and not s.is_goalie),
                    key=lambda s: (s.pos - skater.pos).length(),
                    default=None,
                )
                if nearest_opp is not None and (nearest_opp.pos - skater.pos).length() < CHECK_RADIUS:
                    if resolve_check(skater, nearest_opp, self.puck):
                        self.spawn_hit_particles((skater.pos + nearest_opp.pos) / 2)
                        self.shake_camera(4, 10)
                        self.sounds["check"].play()

        resolve_skater_collisions(self.all_skaters)

        # puck possession: a single skater nearby grabs it instantly, but if 2+ opposing
        # skaters are both right on it (boards/net-front scrum), it's a contested battle.
        if self.puck.carrier is None and self.puck.cooldown == 0:
            contestants = [
                skater for skater in self.all_skaters
                if not skater.is_goalie and (skater.pos - self.puck.pos).length() < PICKUP_RADIUS
            ]
            teams_present = {s.team for s in contestants}
            if len(contestants) == 1:
                self.puck.carrier = contestants[0]
                self.puck.save_rolled = True
            elif len(teams_present) >= 2:
                winner = resolve_puck_battle(contestants, self.puck)
                if winner is not None:
                    self.puck.carrier = winner
                    self.puck.save_rolled = True
            elif contestants:
                # several teammates on it together with no opponent contesting - no battle needed
                self.puck.carrier = contestants[0]
                self.puck.save_rolled = True


        # steal check
        if self.puck.carrier is not None and self.puck.carrier.deke_timer == 0:
            carrier = self.puck.carrier
            for skater in self.all_skaters:
                if skater is carrier or skater.team == carrier.team or skater.is_goalie:
                    continue
                if (skater.pos - carrier.pos).length() < STEAL_RADIUS:
                    if random.random() < skater.steal * 0.05:
                        self.puck.carrier = None
                        self.puck.vel = (carrier.pos - skater.pos).normalize() * 3 if (carrier.pos - skater.pos).length() > 0 else Vector2(0, 0)
                        self.puck.cooldown = PUCK_COOLDOWN_FRAMES

        # goalie save: one probabilistic roll per shot, not a guaranteed block every frame
        if self.puck.carrier is None and not self.puck.save_rolled:
            for skater in self.all_skaters:
                if skater.is_goalie and (skater.pos - self.puck.pos).length() < skater.radius + self.puck.radius + 4:
                    self.puck.save_rolled = True
                    if random.random() < 0.55:
                        clear_dir = Vector2(1, random.uniform(-0.4, 0.4)) if skater.team == "left" else Vector2(-1, random.uniform(-0.4, 0.4))
                        self.puck.vel = clear_dir.normalize() * 6
                        self.puck.cooldown = PUCK_COOLDOWN_FRAMES
                        self.sounds["hit"].play()
                    break

        self.update_sprays()
        self.update_hit_particles()
        self.update_shake()
        goal = self.puck.update()

        event_happened = False
        if goal:
            self.score[goal] += 1
            self.message = f"GOAL! {'You' if goal == 'left' else 'CPU'} score!"
            self.message_timer = FPS * 2
            self.sounds["whistle"].play()
            self.sounds["goal_horn"].play()
            self.sounds["crowd_cheer"].play()
            self.goal_replay_team = goal
            self.goal_replay_timer = GOAL_REPLAY_FRAMES
            # faceoff reset and clock countdown are deferred until the replay
            # window finishes (see the goal_replay_timer branch above)
            return True

        self.time_left -= dt_frames
        if self.time_left <= 0:
            self.sounds["whistle"].play()
            if self.period >= 3:
                self.enter_state("GAME_OVER")
            else:
                self.period += 1
                self.time_left = PERIOD_SECONDS * FPS
                self.reset_positions(None)
            event_happened = True

        return event_happened

    def user_shoot(self):
        user = self.user_skater()
        if self.puck.carrier is user and user.shoot_cooldown == 0:
            resolve_shoot(user, self.puck, RINK_RIGHT)
            self.sounds["shoot"].play()

    def user_deke(self):
        self.user_skater().try_deke()

    def user_check(self):
        user = self.user_skater()
        nearest = None
        nearest_dist = CHECK_RADIUS
        for skater in self.all_skaters:
            if skater.team == user.team or skater.is_goalie:
                continue
            dist = (skater.pos - user.pos).length()
            if dist < nearest_dist:
                nearest = skater
                nearest_dist = dist
        if nearest is not None:
            if resolve_check(user, nearest, self.puck):
                self.spawn_hit_particles((user.pos + nearest.pos) / 2)
                self.shake_camera(4, 10)
                self.sounds["check"].play()

    def proj(self, world_pos):
        result = self.camera.project(world_pos)
        if result is None:
            return None
        screen_x, screen_y, scale, depth = result
        screen_x += self.shake_offset.x
        screen_y += self.shake_offset.y
        scale *= self.zoom_scale
        return screen_x, screen_y, scale, depth

    def build_crowd_texture(self):
        crowd_texture = pygame.Surface((WIDTH, HORIZON_Y), pygame.SRCALPHA)

        for i in range(HORIZON_Y):
            t = i / HORIZON_Y
            shade = (int(20 + 18 * t), int(14 + 14 * t), int(28 + 22 * t))
            pygame.draw.line(crowd_texture, shade, (0, i), (WIDTH, i))
        for sx in range(0, WIDTH, 26):
            pygame.draw.rect(crowd_texture, (40, 30, 55), (sx, HORIZON_Y - 55, 16, 55))

        base_hues = [
            (60, 90, 150),   # dim blue
            (140, 70, 70),   # dim red
            (150, 120, 60),  # dim gold
            (90, 90, 95),    # grey
        ]
        for _ in range(300):
            x = random.randint(0, WIDTH - 2)
            y = random.randint(0, HORIZON_Y - HORIZON_Y // 3)
            r, g, b = random.choice(base_hues)
            jitter = random.randint(-15, 15)
            color = (
                clamp(r + jitter, 0, 255),
                clamp(g + jitter, 0, 255),
                clamp(b + jitter, 0, 255),
            )
            pygame.draw.rect(crowd_texture, color, (x, y, 2, 3))

        return crowd_texture

    def draw_rink(self):
        self.screen.fill((8, 9, 16))

        # crowd/arena backdrop above the horizon for atmosphere - pre-rendered once and
        # reused every frame (same lesson as the ice glow: a per-pixel/per-dot loop here
        # would be a fixed per-frame cost even though the crowd never moves or changes)
        if not hasattr(self, "_crowd_texture"):
            self._crowd_texture = self.build_crowd_texture()
        self.screen.blit(self._crowd_texture, (0, 0))

        # ice stretching from the horizon to the bottom of the screen
        ice_rect = pygame.Rect(0, HORIZON_Y, WIDTH, HEIGHT - HORIZON_Y)
        for i in range(ice_rect.height):
            t = i / ice_rect.height
            shade = (int(ICE[0] - 55 * (1 - t)), int(ICE[1] - 45 * (1 - t)), int(ICE[2] - 35 * (1 - t)))
            pygame.draw.line(self.screen, shade, (0, HORIZON_Y + i), (WIDTH, HORIZON_Y + i))
        pygame.draw.line(self.screen, (230, 235, 245), (0, HORIZON_Y), (WIDTH, HORIZON_Y), 2)

        # subtle diagonal scratch texture on the ice
        for sx in range(0, WIDTH, 20):
            for sy in range(HORIZON_Y, HEIGHT, 20):
                if (sx + (sy - HORIZON_Y)) % 40 == 0:
                    pygame.draw.line(self.screen, (225, 235, 250), (sx, sy), (sx + 10, sy + 10))

        # soft radial light-reflection gradient, pre-rendered once and reused every frame
        if not hasattr(self, "_ice_glow"):
            glow_h = HEIGHT - HORIZON_Y
            glow = pygame.Surface((WIDTH, glow_h), pygame.SRCALPHA)
            center = (WIDTH // 2, glow_h // 3)
            radius = min(WIDTH, glow_h) // 2
            for r in range(radius, 0, -4):
                alpha = int(28 * (1 - r / radius))
                pygame.draw.circle(glow, (255, 255, 255, alpha), center, r)
            self._ice_glow = glow
        self.screen.blit(self._ice_glow, (0, HORIZON_Y))

        self.draw_ground_polyline(RINK_TOP, BOARD, 4)
        self.draw_ground_polyline(RINK_BOTTOM, BOARD, 4)

        center_y_world = HEIGHT / 2
        blue_x_left = RINK_LEFT + (WIDTH / 2 - RINK_LEFT) * 0.62
        blue_x_right = RINK_RIGHT - (RINK_RIGHT - WIDTH / 2) * 0.62

        self.draw_ground_segment((blue_x_left, RINK_TOP), (blue_x_left, RINK_BOTTOM), BLUE, 4)
        self.draw_ground_segment((blue_x_right, RINK_TOP), (blue_x_right, RINK_BOTTOM), BLUE, 4)
        self.draw_ground_segment((WIDTH / 2, RINK_TOP), (WIDTH / 2, RINK_BOTTOM), RED, 3)

        p = self.proj((WIDTH / 2, center_y_world))
        if p:
            sx, sy, scale, _ = p
            pygame.draw.ellipse(self.screen, RED, (sx - 52 * scale, sy - 20 * scale, 104 * scale, 40 * scale), max(1, int(2 * scale)))

        for fx in (RINK_LEFT + 90, blue_x_left + 60, blue_x_right - 60, RINK_RIGHT - 90):
            for fy in (center_y_world - 110, center_y_world + 110):
                dp = self.proj((fx, fy))
                if dp:
                    sx, sy, scale, _ = dp
                    pygame.draw.circle(self.screen, RED, (int(sx), int(sy)), max(1, int(5 * scale)))

        self.draw_goal_billboard(RINK_LEFT, (90, 160, 230))
        self.draw_goal_billboard(RINK_RIGHT, (230, 90, 90))

    def draw_ground_polyline(self, world_y, color, width):
        points = []
        for wx in range(RINK_LEFT - 40, RINK_RIGHT + 41, 16):
            p = self.proj((wx, world_y))
            if p:
                points.append((p[0], p[1]))
        if len(points) >= 2:
            pygame.draw.lines(self.screen, color, False, points, width)

    def draw_ground_segment(self, world_a, world_b, color, width):
        pa = self.proj(world_a)
        pb = self.proj(world_b)
        if pa and pb:
            pygame.draw.line(self.screen, color, (pa[0], pa[1]), (pb[0], pb[1]), width)

    def draw_goal_billboard(self, goal_x, net_color):
        center_y = HEIGHT / 2
        p = self.proj((goal_x, center_y))
        if not p:
            return
        sx, sy, scale, _ = p
        if scale <= 0.01:
            return
        width_px = GOAL_HEIGHT * scale
        height_px = 46 * scale
        rect = pygame.Rect(0, 0, width_px, height_px)
        rect.midbottom = (sx, sy)
        pygame.draw.rect(self.screen, GOAL_COLOR, rect, width=max(1, int(3 * scale)))
        for gy in range(int(rect.top) + 6, int(rect.bottom), max(2, int(14 * scale))):
            pygame.draw.line(self.screen, (120, 120, 130), (rect.left, gy), (rect.right, gy), 1)
        crease = pygame.Surface((max(1, int(width_px)), max(1, int(height_px * 0.5))), pygame.SRCALPHA)
        pygame.draw.ellipse(crease, (*net_color, 70), crease.get_rect())
        self.screen.blit(crease, (rect.left, rect.bottom - crease.get_height() // 2))

    def draw_hud(self):
        panel = pygame.Surface((WIDTH, 70), pygame.SRCALPHA)
        for y in range(70):
            t = y / 70
            shade = int(10 + 14 * (1 - t))
            pygame.draw.line(panel, (shade, shade + 2, shade + 10, 210), (0, y), (WIDTH, y))
        self.screen.blit(panel, (0, 0))

        you_label = self.big_font.render(str(self.score["left"]), True, BLUE)
        cpu_label = self.big_font.render(str(self.score["right"]), True, RED)
        dash = self.big_font.render("-", True, WHITE)
        self.screen.blit(self.font.render("YOU", True, BLUE), (WIDTH / 2 - 150, 24))
        self.screen.blit(you_label, (WIDTH / 2 - 100, 14))
        self.screen.blit(dash, (WIDTH / 2 - 8, 14))
        self.screen.blit(cpu_label, (WIDTH / 2 + 30, 14))
        self.screen.blit(self.font.render("CPU", True, RED), (WIDTH / 2 + 80, 24))

        seconds = max(0, self.time_left // FPS)
        clock_rect = pygame.Rect(16, 10, 90, 34)
        pygame.draw.rect(self.screen, (4, 5, 10), clock_rect, border_radius=4)
        pygame.draw.rect(self.screen, (90, 95, 110), clock_rect, 1, border_radius=4)
        self.screen.blit(self.font.render(f"Period {self.period}/3", True, GOLD), (20, 14))
        self.screen.blit(self.font.render(f"{seconds:02d}s", True, WHITE), (20, 38))

        for p in range(1, 4):
            color = GOLD if p <= self.period else (70, 70, 80)
            pygame.draw.circle(self.screen, (0, 0, 0), (150 + p * 16, 25), 6, 1)
            pygame.draw.circle(self.screen, color, (150 + p * 16, 25), 5)

        carrier = self.puck.carrier
        if carrier:
            who = "You" if carrier.is_user else ("Your team" if carrier.team == "left" else "CPU")
            poss = self.font.render(f"Puck: {who}", True, (200, 200, 210))
            self.screen.blit(poss, (WIDTH - poss.get_width() - 20, 24))

        if self.message_timer > 0:
            alpha = clamp(int(255 * self.message_timer / (FPS * 2)), 0, 255)
            label = self.big_font.render(self.message, True, GOLD)
            label.set_alpha(alpha)
            label_rect = label.get_rect(center=(WIDTH / 2, HEIGHT / 2 - 60))
            # a dark backing panel so the gold text stays readable against a
            # close-up skater jersey (same gold) or bright ice behind it
            backing = pygame.Surface((label_rect.width + 40, label_rect.height + 20), pygame.SRCALPHA)
            backing.fill((4, 5, 10, int(180 * alpha / 255)))
            self.screen.blit(backing, backing.get_rect(center=label_rect.center))
            self.screen.blit(label, label_rect)

        self.draw_stamina_bar()

    def draw_stamina_bar(self):
        user = self.user_skater()
        bar_w, bar_h = 200, 14
        x, y = 20, HEIGHT - 32
        pct = user.stamina / 100.0
        pygame.draw.rect(self.screen, (30, 30, 35), (x, y, bar_w, bar_h), border_radius=5)
        if pct > 0.5:
            fill_color = (90, 210, 110)
        elif pct > 0.2:
            fill_color = (230, 190, 60)
        else:
            fill_color = (220, 70, 70)
        pygame.draw.rect(self.screen, fill_color, (x, y, int(bar_w * pct), bar_h), border_radius=5)
        pygame.draw.rect(self.screen, WHITE, (x, y, bar_w, bar_h), width=1, border_radius=5)
        label = self.small_font.render("STAMINA (Shift=sprint, E=deke, Ctrl=strafe, C=check)", True, (210, 210, 215))
        self.screen.blit(label, (x, y - 16))

    def draw_sprays(self):
        # ice spray kicked up by sharp turns/hard stops, sells the "digging an edge" feel.
        # Faded by blending toward the ice color (cheaper than per-particle alpha surfaces).
        for s in self.sprays:
            p = self.proj(s["pos"])
            if not p:
                continue
            sx, sy, scale, _ = p
            fade = clamp(s["life"] / 18, 0.0, 1.0)
            color = tuple(int(ICE[i] + (255 - ICE[i]) * fade) for i in range(3))
            end = (sx - s["vel"].x * scale, sy - s["vel"].y * scale)
            pygame.draw.line(self.screen, color, (sx, sy), end, max(1, int(2 * scale)))

    def draw_hit_particles(self):
        for h in self.hit_particles:
            p = self.proj(h["pos"])
            if not p:
                continue
            hx, hy, scale, _ = p
            color = (255, 230, 120)
            end = (hx - h["vel"].x * scale, hy - h["vel"].y * scale)
            pygame.draw.line(self.screen, color, (hx, hy), end, max(1, int(2 * scale)))

    def draw_shot_reticle(self):
        user = self.user_skater()
        if self.puck.carrier is not user or user.shoot_cooldown > 0:
            return
        goal_top = HEIGHT / 2 - GOAL_HEIGHT / 2 + 10
        goal_bottom = HEIGHT / 2 + GOAL_HEIGHT / 2 - 10
        aim_y = clamp(user.pos.y + user.facing.y * 150, goal_top, goal_bottom)
        p = self.proj((RINK_RIGHT, aim_y))
        if not p:
            return
        sx, sy, scale, _ = p
        size = clamp(14 * scale, 6, 60)
        color = GOLD
        for sign in (-1, 1):
            cy = sy + sign * size
            pygame.draw.line(self.screen, color, (sx - size, cy), (sx - size + size * 0.4, cy), 2)
            pygame.draw.line(self.screen, color, (sx + size, cy), (sx + size - size * 0.4, cy), 2)
            pygame.draw.line(self.screen, color, (sx - size, cy), (sx - size, cy - sign * size * 0.4), 2)
            pygame.draw.line(self.screen, color, (sx + size, cy), (sx + size, cy - sign * size * 0.4), 2)

    def draw_skaters_and_puck(self):
        # painter's algorithm: draw farthest-from-camera first so nearer things overlap correctly
        entities = [("skater", s) for s in self.all_skaters] + [("puck", self.puck)]
        projected = []
        for kind, obj in entities:
            p = self.proj(obj.pos)
            if p is None:
                continue
            sx, sy, scale, depth = p
            projected.append((depth, kind, obj, sx, sy, scale))
        projected.sort(key=lambda e: -e[0])

        for depth, kind, obj, sx, sy, scale in projected:
            if kind == "puck":
                trail_len = len(self.puck.trail)
                for i, trail_pos in enumerate(self.puck.trail):
                    trail_proj = self.proj(trail_pos)
                    if trail_proj is None:
                        continue
                    trail_sx, trail_sy, trail_scale, _ = trail_proj
                    taper = 0.3 + 0.5 * (i / max(trail_len - 1, 1))
                    self._draw_puck_billboard(trail_sx, trail_sy, trail_scale * taper)
                self._draw_puck_billboard(sx, sy, scale)
            else:
                self._draw_skater_billboard(obj, sx, sy, scale)

    def _draw_skater_billboard(self, skater, sx, sy, scale):
        if scale <= 0.01:
            return
        r_px = clamp(skater.radius * scale * 2.1, 1.5, 90)
        speed_ratio = clamp(skater.vel.length() / skater.speed if skater.speed else 0, 0, 1)

        # fading skate trail projected as small ground dots behind the skater
        if len(skater.trail) >= 2:
            for i in range(len(skater.trail) - 1):
                tp = self.proj(skater.trail[i])
                if not tp:
                    continue
                t = i / len(skater.trail)
                alpha = int(80 * t * speed_ratio)
                if alpha <= 2:
                    continue
                tsx, tsy, tscale, _ = tp
                dot_r = max(1, int(2 * tscale))
                trail_surf = pygame.Surface((dot_r * 2 + 2, dot_r * 2 + 2), pygame.SRCALPHA)
                pygame.draw.circle(trail_surf, (*skater.color[:3], alpha), (dot_r + 1, dot_r + 1), dot_r)
                self.screen.blit(trail_surf, (tsx - dot_r - 1, tsy - dot_r - 1))

        shadow = pygame.Surface((int(r_px * 2.6) + 4, int(r_px * 0.9) + 4), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 90), shadow.get_rect())
        self.screen.blit(shadow, (sx - shadow.get_width() / 2, sy - shadow.get_height() / 2))

        top_y = self._draw_human_figure(skater, sx, sy, r_px, scale, speed_ratio)

        if self.puck.carrier is skater:
            glow_center = (sx, sy - r_px * 2.0)
            pygame.draw.circle(self.screen, (255, 255, 255), glow_center, r_px * 1.5 + max(2, 4 * scale), max(1, int(2 * scale)))

        if skater.label:
            tag = skater.label if skater.is_goalie else f"{skater.label} #{skater.jersey_number}"
            font = self.small_font if scale < 1.3 else self.font
            label = font.render(tag, True, WHITE)
            self.screen.blit(label, label.get_rect(center=(sx, top_y - 10)))
        if skater.sprinting:
            spark = self.small_font.render("*", True, GOLD)
            self.screen.blit(spark, (sx + r_px, sy - r_px * 3.4))

    def _draw_human_figure(self, skater, sx, sy, r_px, scale, speed_ratio):
        """Draws a simple stylized skater (helmet, jersey torso, skating legs, stick) as a
        screen-space billboard anchored at the ground point (sx, sy). Returns the head's top y."""
        color = GOLD if skater.is_user else skater.color
        outline_w = max(1, int(2 * scale))

        leg_len = r_px * 1.9
        torso_h = r_px * 1.9
        torso_w = r_px * 1.5
        head_r = r_px * 0.62

        hip_y = sy - leg_len
        shoulder_y = hip_y - torso_h
        head_cy = shoulder_y - head_r * 1.15

        # legs: alternate stride via a phase that advances with movement, for a skating look
        stride = math.sin(skater.stride_phase) if not skater.is_goalie else 0.0
        leg_spread = r_px * (0.55 + 0.35 * speed_ratio)
        foot_l = (sx - leg_spread * (1 + 0.5 * stride), sy)
        foot_r = (sx + leg_spread * (1 - 0.5 * stride), sy)
        pants_color = (35, 35, 40)
        leg_w = max(2, int(r_px * 0.42))
        pygame.draw.line(self.screen, pants_color, (sx, hip_y), foot_l, leg_w)
        pygame.draw.line(self.screen, pants_color, (sx, hip_y), foot_r, leg_w)
        pygame.draw.circle(self.screen, (15, 15, 18), foot_l, max(1, leg_w * 0.55))
        pygame.draw.circle(self.screen, (15, 15, 18), foot_r, max(1, leg_w * 0.55))

        # torso (jersey), slightly stretched when sprinting and tilted into turns
        torso_surf = pygame.Surface((max(2, int(torso_w)), max(2, int(torso_h))), pygame.SRCALPHA)
        pygame.draw.rect(torso_surf, color, torso_surf.get_rect(), border_radius=max(1, int(torso_w * 0.3)))
        pygame.draw.rect(torso_surf, BLACK, torso_surf.get_rect(), width=outline_w, border_radius=max(1, int(torso_w * 0.3)))
        tilt = skater.lean * 9
        rotated_torso = pygame.transform.rotate(torso_surf, tilt)
        torso_center = (sx, (hip_y + shoulder_y) / 2)
        self.screen.blit(rotated_torso, rotated_torso.get_rect(center=torso_center))

        # arms + stick, angled toward the puck side
        stick_color = (90, 65, 40)
        shoulder_x_off = torso_w * 0.42
        arm_end = (sx + shoulder_x_off * 1.6, hip_y + leg_len * 0.1)
        pygame.draw.line(self.screen, color, (sx - shoulder_x_off, shoulder_y + torso_h * 0.2), arm_end, max(1, int(r_px * 0.28)))
        stick_tip = (arm_end[0] + r_px * 0.9, sy - r_px * 0.1)
        pygame.draw.line(self.screen, stick_color, arm_end, stick_tip, max(1, int(r_px * 0.18)))

        # head / helmet
        helmet_color = (25, 25, 30) if not skater.is_user else (90, 60, 10)
        pygame.draw.circle(self.screen, helmet_color, (sx, head_cy), head_r)
        pygame.draw.circle(self.screen, color, (sx, head_cy), head_r * 0.72)
        pygame.draw.circle(self.screen, BLACK, (sx, head_cy), head_r, outline_w)

        return head_cy - head_r

    def _draw_puck_billboard(self, sx, sy, scale):
        if scale <= 0.01:
            return
        r_px = clamp(self.puck.radius * scale * 1.8, 1.0, 40)
        shadow = pygame.Surface((int(r_px * 2.4) + 4, int(r_px * 1.2) + 4), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 100), shadow.get_rect())
        self.screen.blit(shadow, (sx - shadow.get_width() / 2, sy - shadow.get_height() / 2))
        pygame.draw.circle(self.screen, PUCK_COLOR, (sx, sy), r_px)
        pygame.draw.circle(self.screen, (70, 70, 75), (sx, sy), r_px, max(1, int(scale)))
        pygame.draw.circle(self.screen, (90, 90, 95), (sx - r_px * 0.3, sy - r_px * 0.3), max(1, r_px / 3))

    def draw_game_over(self):
        self.screen.fill(BLACK)
        winner = "You win!" if self.score["left"] > self.score["right"] else (
            "CPU wins." if self.score["right"] > self.score["left"] else "It's a tie."
        )
        title = self.big_font.render("Game Over", True, GOLD)
        result = self.big_font.render(f"Final: {self.score['left']} - {self.score['right']}", True, WHITE)
        sub = self.font.render(winner, True, WHITE)
        self.screen.blit(title, title.get_rect(center=(WIDTH / 2, 220)))
        self.screen.blit(result, result.get_rect(center=(WIDTH / 2, 280)))
        self.screen.blit(sub, sub.get_rect(center=(WIDTH / 2, 320)))
        hint = self.font.render("Press R to play again, ESC to quit", True, (160, 160, 170))
        self.screen.blit(hint, hint.get_rect(center=(WIDTH / 2, 380)))

    def draw_title(self):
        self.screen.fill(BLACK)
        title = self.big_font.render("HOCKEY ARCADE", True, GOLD)
        subtitle = self.font.render("Behind-the-boards 3rd-person hockey", True, WHITE)
        controls = [
            self.font.render("WASD / Arrows: Skate", True, (160, 160, 170)),
            self.font.render("Shift: Sprint", True, (160, 160, 170)),
            self.font.render("Space: Shoot", True, (160, 160, 170)),
            self.font.render("E or F: Deke", True, (160, 160, 170)),
            self.font.render("C: Check", True, (160, 160, 170)),
            self.font.render("Ctrl: Strafe (face the puck while moving freely)", True, (160, 160, 170)),
        ]
        start_prompt = self.big_font.render("Press ENTER to start", True, GOLD)
        start_prompt.set_alpha(int(150 + 105 * abs(math.sin(pygame.time.get_ticks() / 1000.0))))

        self.screen.blit(title, title.get_rect(center=(WIDTH / 2, 90)))
        self.screen.blit(subtitle, subtitle.get_rect(center=(WIDTH / 2, 135)))
        for i, line in enumerate(controls):
            self.screen.blit(line, line.get_rect(center=(WIDTH / 2, 195 + i * 32)))
        self.screen.blit(start_prompt, start_prompt.get_rect(center=(WIDTH / 2, 430)))

    def draw(self):
        if self.state == "TITLE":
            self.draw_title()
        elif self.state == "GAME_OVER":
            self.draw_game_over()
        else:
            self.draw_rink()
            self.draw_shot_reticle()
            self.draw_sprays()
            self.draw_skaters_and_puck()
            self.draw_hit_particles()
            self.draw_hud()
        pygame.display.flip()

    def run(self):
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif self.state == "TITLE" and event.key == pygame.K_RETURN:
                        self.enter_state("PLAYING")
                    elif self.state == "GAME_OVER" and event.key == pygame.K_r:
                        self.start_new_game()
                    elif self.state == "PLAYING" and event.key == pygame.K_SPACE:
                        self.user_shoot()
                    elif self.state == "PLAYING" and event.key in (pygame.K_e, pygame.K_f):
                        self.user_deke()
                    elif self.state == "PLAYING" and event.key == pygame.K_c:
                        self.user_check()
            self.step()
            self.draw()
            self.clock.tick(FPS)
        pygame.quit()


if __name__ == "__main__":
    ArcadeGame().run()
