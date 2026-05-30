"""
8-Ball Pool Oyunu — Python + Pygame
Kurulum: pip install pygame
Çalıştırma: python pool_game.py
"""

import pygame
import math
import sys
import random

# ─── Sabitler ───────────────────────────────────────────────────────────────
W, H = 1200, 700
TABLE_X, TABLE_Y = 60, 80
TABLE_W, TABLE_H = 1080, 540
BALL_R = 14
CUE_WIDTH = 8
FRICTION = 0.985
MIN_SPEED = 0.15
POCKET_R = 22

# Renkler
C_FELT       = (34, 110, 60)
C_FELT_DARK  = (25, 85, 45)
C_CUSHION    = (20, 70, 35)
C_WOOD       = (90, 50, 15)
C_BG         = (18, 18, 22)
C_WHITE      = (255, 255, 255)
C_BLACK      = (20, 20, 20)
C_YELLOW     = (240, 200, 30)
C_BLUE       = (30, 80, 200)
C_RED        = (210, 40, 40)
C_PURPLE     = (120, 40, 160)
C_ORANGE     = (230, 110, 20)
C_GREEN      = (40, 160, 60)
C_MAROON     = (140, 20, 20)
C_TEAL       = (20, 140, 140)
C_CUE_LINE   = (255, 255, 180)
C_POCKET     = (10, 10, 10)
C_POWER_BG   = (40, 40, 50)
C_POWER_FG   = (80, 200, 120)
C_POWER_HIGH = (220, 80, 60)
C_TEXT       = (220, 220, 220)
C_SHADOW     = (0, 0, 0, 80)

# Top tanımları: (numara, ana_renk, şerit_mi, etiket_rengi)
BALL_DEFS = [
    (0,  C_WHITE,  False, C_BLACK),   # top (beyaz)
    (1,  C_YELLOW, False, C_WHITE),
    (2,  C_BLUE,   False, C_WHITE),
    (3,  C_RED,    False, C_WHITE),
    (4,  C_PURPLE, False, C_WHITE),
    (5,  C_ORANGE, False, C_WHITE),
    (6,  C_GREEN,  False, C_WHITE),
    (7,  C_MAROON, False, C_WHITE),
    (8,  C_BLACK,  False, C_WHITE),   # 8-top
    (9,  C_YELLOW, True,  C_BLACK),
    (10, C_BLUE,   True,  C_WHITE),
    (11, C_RED,    True,  C_WHITE),
    (12, C_PURPLE, True,  C_WHITE),
    (13, C_ORANGE, True,  C_WHITE),
    (14, C_GREEN,  True,  C_WHITE),
    (15, C_MAROON, True,  C_WHITE),
]

POCKETS = [
    (TABLE_X + 18,           TABLE_Y + 18),
    (TABLE_X + TABLE_W // 2, TABLE_Y + 4),
    (TABLE_X + TABLE_W - 18, TABLE_Y + 18),
    (TABLE_X + 18,           TABLE_Y + TABLE_H - 18),
    (TABLE_X + TABLE_W // 2, TABLE_Y + TABLE_H + 4),
    (TABLE_X + TABLE_W - 18, TABLE_Y + TABLE_H - 18),
]


# ─── Yardımcı ──────────────────────────────────────────────────────────────
def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])

def normalize(dx, dy):
    d = math.hypot(dx, dy)
    if d == 0:
        return 0, 0
    return dx / d, dy / d


# ─── Top sınıfı ────────────────────────────────────────────────────────────
class Ball:
    def __init__(self, num, x, y):
        self.num = num
        self.x, self.y = float(x), float(y)
        self.vx, self.vy = 0.0, 0.0
        self.pocketed = False
        info = BALL_DEFS[num]
        self.color = info[1]
        self.stripe = info[2]
        self.label_color = info[3]

    @property
    def moving(self):
        return math.hypot(self.vx, self.vy) > MIN_SPEED

    def update(self):
        if self.pocketed:
            return
        self.x += self.vx
        self.y += self.vy
        self.vx *= FRICTION
        self.vy *= FRICTION
        if math.hypot(self.vx, self.vy) < MIN_SPEED:
            self.vx = self.vy = 0.0
        # Yastık çarpışması
        lx = TABLE_X + BALL_R + 14
        rx = TABLE_X + TABLE_W - BALL_R - 14
        ty = TABLE_Y + BALL_R + 14
        by = TABLE_Y + TABLE_H - BALL_R - 14
        if self.x < lx:
            self.x = lx; self.vx = abs(self.vx) * 0.75
        if self.x > rx:
            self.x = rx; self.vx = -abs(self.vx) * 0.75
        if self.y < ty:
            self.y = ty; self.vy = abs(self.vy) * 0.75
        if self.y > by:
            self.y = by; self.vy = -abs(self.vy) * 0.75

    def collide(self, other):
        if self.pocketed or other.pocketed:
            return
        dx = other.x - self.x
        dy = other.y - self.y
        d = math.hypot(dx, dy)
        if d < BALL_R * 2 and d > 0:
            nx, ny = dx / d, dy / d
            # Örtüşmeyi çöz
            overlap = BALL_R * 2 - d
            self.x -= nx * overlap / 2
            self.y -= ny * overlap / 2
            other.x += nx * overlap / 2
            other.y += ny * overlap / 2
            # Hız değişimi
            dvx = self.vx - other.vx
            dvy = self.vy - other.vy
            dot = dvx * nx + dvy * ny
            if dot > 0:
                self.vx -= dot * nx
                self.vy -= dot * ny
                other.vx += dot * nx
                other.vy += dot * ny

    def draw(self, surf, font_sm):
        if self.pocketed:
            return
        x, y = int(self.x), int(self.y)
        r = BALL_R
        # Gölge
        pygame.draw.circle(surf, (0, 0, 0), (x + 3, y + 4), r)
        # Top gövdesi
        pygame.draw.circle(surf, self.color, (x, y), r)
        if self.stripe:
            # Şerit efekti — yatay bant
            stripe_rect = pygame.Rect(x - r, y - r // 2, r * 2, r)
            clip = surf.get_clip()
            # Çember kırpma için surface
            mask_surf = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(mask_surf, self.color, (r, r), r)
            pygame.draw.rect(mask_surf, C_WHITE, (0, r // 2, r * 2, r))
            surf.blit(mask_surf, (x - r, y - r))
        # Parlama
        pygame.draw.circle(surf, (255, 255, 255), (x - r // 3, y - r // 3), r // 4)
        # Numara (0 = beyaz top, numara gösterme)
        if self.num > 0:
            pygame.draw.circle(surf, C_WHITE, (x, y), r // 2)
            label = font_sm.render(str(self.num), True, C_BLACK)
            surf.blit(label, label.get_rect(center=(x, y)))
        # Kenar
        pygame.draw.circle(surf, (0, 0, 0), (x, y), r, 1)


# ─── Oyun sınıfı ────────────────────────────────────────────────────────────
class PoolGame:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("8-Ball Pool")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Arial", 18, bold=True)
        self.font_sm = pygame.font.SysFont("Arial", 11, bold=True)
        self.font_lg = pygame.font.SysFont("Arial", 32, bold=True)
        self.font_title = pygame.font.SysFont("Arial", 48, bold=True)
        self.reset()

    def reset(self):
        self.balls = self._rack()
        self.shooting = False
        self.drag_start = None
        self.power = 0.0
        self.current_player = 1
        self.score = [0, 0]
        self.message = "Çekin ve bırakın!"
        self.msg_timer = 180
        self.game_over = False
        self.winner = None
        self.shot_count = 0

    def _rack(self):
        balls = []
        # Beyaz top
        balls.append(Ball(0, TABLE_X + TABLE_W // 4, TABLE_Y + TABLE_H // 2))
        # Üçgen diziliş
        cx = TABLE_X + TABLE_W * 3 // 4
        cy = TABLE_Y + TABLE_H // 2
        gap = BALL_R * 2 + 1
        positions = []
        for row in range(5):
            for col in range(row + 1):
                px = cx + row * gap * math.cos(math.radians(30))
                py = cy + (col - row / 2) * gap
                positions.append((px, py))
        nums = [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15]
        random.shuffle(nums)
        # 8'i ortaya koy
        mid = 4
        idx_8 = nums.index(8)
        nums[idx_8], nums[mid] = nums[mid], nums[idx_8]
        for i, (px, py) in enumerate(positions):
            balls.append(Ball(nums[i], px, py))
        return balls

    @property
    def cue_ball(self):
        return self.balls[0]

    @property
    def any_moving(self):
        return any(b.moving for b in self.balls if not b.pocketed)

    def _check_pockets(self):
        pocketed_now = []
        for b in self.balls:
            if b.pocketed:
                continue
            for px, py in POCKETS:
                if dist((b.x, b.y), (px, py)) < POCKET_R:
                    b.pocketed = True
                    pocketed_now.append(b.num)
                    break
        for num in pocketed_now:
            if num == 0:
                self._cue_ball_foul()
            elif num == 8:
                self._eight_ball_pocketed()
            else:
                self.score[self.current_player - 1] += 1
                self.message = f"Top {num} potaya gitti! +1 puan"
                self.msg_timer = 120

    def _cue_ball_foul(self):
        b = self.cue_ball
        b.pocketed = False
        b.x = TABLE_X + TABLE_W // 4
        b.y = TABLE_Y + TABLE_H // 2
        b.vx = b.vy = 0.0
        self.message = "Foul! Beyaz top geri döndü."
        self.msg_timer = 150

    def _eight_ball_pocketed(self):
        self.game_over = True
        self.winner = self.current_player
        self.message = f"Oyuncu {self.current_player} kazandı! 8-top potaya girdi!"

    def shoot(self, power, angle):
        speed = power * 28
        self.cue_ball.vx = math.cos(angle) * speed
        self.cue_ball.vy = math.sin(angle) * speed
        self.shot_count += 1
        self.current_player = 2 if self.current_player == 1 else 1

    def update(self):
        if self.game_over:
            return
        for b in self.balls:
            b.update()
        for i in range(len(self.balls)):
            for j in range(i + 1, len(self.balls)):
                self.balls[i].collide(self.balls[j])
        self._check_pockets()
        if self.msg_timer > 0:
            self.msg_timer -= 1

    def _draw_table(self):
        s = self.screen
        # Arka plan
        s.fill(C_BG)
        # Ahşap çerçeve
        wood_rect = pygame.Rect(TABLE_X - 30, TABLE_Y - 30, TABLE_W + 60, TABLE_H + 60)
        pygame.draw.rect(s, C_WOOD, wood_rect, border_radius=12)
        # Yastıklar
        cushion_rect = pygame.Rect(TABLE_X - 10, TABLE_Y - 10, TABLE_W + 20, TABLE_H + 20)
        pygame.draw.rect(s, C_CUSHION, cushion_rect, border_radius=8)
        # Zemin
        felt_rect = pygame.Rect(TABLE_X, TABLE_Y, TABLE_W, TABLE_H)
        pygame.draw.rect(s, C_FELT, felt_rect)
        # Çizgiler
        cx = TABLE_X + TABLE_W // 4
        pygame.draw.line(s, C_FELT_DARK, (cx, TABLE_Y + 10), (cx, TABLE_Y + TABLE_H - 10), 1)
        # D yarım dairesi
        pygame.draw.arc(s, C_FELT_DARK,
                        pygame.Rect(cx - 60, TABLE_Y + TABLE_H // 2 - 60, 120, 120),
                        math.pi / 2, 3 * math.pi / 2, 1)
        # Potalar
        for px, py in POCKETS:
            pygame.draw.circle(s, C_POCKET, (px, py), POCKET_R)
            pygame.draw.circle(s, (5, 5, 5), (px, py), POCKET_R - 2)

    def _draw_cue(self, mx, my):
        cb = self.cue_ball
        if cb.pocketed:
            return
        dx = cb.x - mx
        dy = cb.y - my
        d = math.hypot(dx, dy)
        if d < 1:
            return
        nx, ny = dx / d, dy / d
        # Yönlendirme çizgisi (noktalı)
        steps = int(min(d + 300, 600) // 12)
        for i in range(steps):
            lx = cb.x + nx * i * 12
            ly = cb.y + ny * i * 12
            if i % 2 == 0:
                pygame.draw.circle(self.screen, (255, 255, 200, 150), (int(lx), int(ly)), 1)
        # Kü
        cue_start_x = cb.x + nx * (BALL_R + 6 + self.power * 40)
        cue_start_y = cb.y + ny * (BALL_R + 6 + self.power * 40)
        cue_end_x = cue_start_x + nx * 260
        cue_end_y = cue_start_y + ny * 260
        # Kü gölgesi
        pygame.draw.line(self.screen, (0, 0, 0),
                         (int(cue_start_x) + 2, int(cue_start_y) + 2),
                         (int(cue_end_x) + 2, int(cue_end_y) + 2), CUE_WIDTH + 1)
        # Kü gövdesi (ince uçtan kalın dibe gradient etkisi)
        pygame.draw.line(self.screen, (210, 160, 80),
                         (int(cue_start_x), int(cue_start_y)),
                         (int(cue_end_x), int(cue_end_y)), CUE_WIDTH)
        pygame.draw.line(self.screen, (240, 200, 120),
                         (int(cue_start_x), int(cue_start_y)),
                         (int(cue_end_x), int(cue_end_y)), CUE_WIDTH // 2)
        # Tebeşir ucu
        pygame.draw.circle(self.screen, (100, 180, 200),
                           (int(cue_start_x), int(cue_start_y)), 4)

    def _draw_power_bar(self):
        bar_x, bar_y = W - 160, H - 60
        bar_w, bar_h = 140, 18
        pygame.draw.rect(self.screen, C_POWER_BG, (bar_x, bar_y, bar_w, bar_h), border_radius=4)
        fill = int(self.power * bar_w)
        color = C_POWER_FG if self.power < 0.7 else C_POWER_HIGH
        if fill > 0:
            pygame.draw.rect(self.screen, color, (bar_x, bar_y, fill, bar_h), border_radius=4)
        pygame.draw.rect(self.screen, C_TEXT, (bar_x, bar_y, bar_w, bar_h), 1, border_radius=4)
        label = self.font.render("Güç", True, C_TEXT)
        self.screen.blit(label, (bar_x, bar_y - 22))

    def _draw_ui(self):
        s = self.screen
        # Başlık
        title = self.font_lg.render("8-Ball Pool", True, (200, 180, 120))
        s.blit(title, (W // 2 - title.get_width() // 2, 12))
        # Skor
        p1 = self.font.render(f"Oyuncu 1: {self.score[0]} top", True,
                               (255, 220, 80) if self.current_player == 1 else C_TEXT)
        p2 = self.font.render(f"Oyuncu 2: {self.score[1]} top", True,
                               (255, 220, 80) if self.current_player == 2 else C_TEXT)
        s.blit(p1, (20, 20))
        s.blit(p2, (20, 46))
        # Sıra
        turn = self.font.render(f"Sıra: Oyuncu {self.current_player}", True, (100, 220, 140))
        s.blit(turn, (20, H - 36))
        # Vuruş sayısı
        shots = self.font.render(f"Vuruş: {self.shot_count}", True, C_TEXT)
        s.blit(shots, (20, H - 60))
        # Mesaj
        if self.msg_timer > 0:
            alpha = min(255, self.msg_timer * 4)
            msg_surf = self.font.render(self.message, True, (255, 230, 100))
            s.blit(msg_surf, (W // 2 - msg_surf.get_width() // 2, H - 36))
        # Talimatlar
        hint = self.font_sm.render("Sürükle → güç  |  Bırak → vur  |  R → yeniden başlat", True, (120, 120, 140))
        s.blit(hint, (W // 2 - hint.get_width() // 2, H - 16))

    def _draw_game_over(self):
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))
        msg = self.font_title.render(f"Oyuncu {self.winner} Kazandı!", True, (255, 220, 60))
        sub = self.font_lg.render("R tuşuna basın — yeniden oyna", True, C_WHITE)
        self.screen.blit(msg, msg.get_rect(center=(W // 2, H // 2 - 30)))
        self.screen.blit(sub, sub.get_rect(center=(W // 2, H // 2 + 40)))

    def run(self):
        dragging = False
        drag_origin = None

        while True:
            mx, my = pygame.mouse.get_pos()
            cb = self.cue_ball

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit(); sys.exit()
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_r:
                        self.reset()
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if not self.any_moving and not self.game_over and not cb.pocketed:
                        dragging = True
                        drag_origin = (mx, my)
                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if dragging and not self.game_over:
                        if self.power > 0.05:
                            dx = drag_origin[0] - mx
                            dy = drag_origin[1] - my
                            angle = math.atan2(dy, dx)
                            # Açıyı toptan fareye doğru hesapla
                            angle = math.atan2(cb.y - drag_origin[1], cb.x - drag_origin[0])
                            self.shoot(self.power, angle)
                        dragging = False
                        drag_origin = None
                        self.power = 0.0

            # Güç hesapla
            if dragging and drag_origin:
                dx = drag_origin[0] - mx
                dy = drag_origin[1] - my
                self.power = min(1.0, math.hypot(dx, dy) / 180)

            self.update()

            # Çizim
            self._draw_table()
            for b in self.balls:
                b.draw(self.screen, self.font_sm)
            if not self.any_moving and not self.game_over and not cb.pocketed:
                self._draw_cue(mx, my)
            if dragging:
                self._draw_power_bar()
            self._draw_ui()
            if self.game_over:
                self._draw_game_over()

            pygame.display.flip()
            self.clock.tick(60)


if __name__ == "__main__":
    PoolGame().run()