// case_params.scad — Gemeinsame Maße für Unterteil und Deckel
// Wird per `include <case_params.scad>` in beide eingebunden.

// ════════════════════════════════════════════════════════════════════
//  HAUPTMASSE — 1-DIN Standard
// ════════════════════════════════════════════════════════════════════

W  = 180;     // Breite
H  = 50;      // Gesamthöhe
D  = 170;     // Tiefe
T  = 2.4;     // Wandstärke
R  = 3;       // Eckenradius

// Trennlinie (Höhe Unterteil-Wände + Frontplatte)
SZ = 30;      // 60 % der Höhe → Frontplatte vollständig im Unterteil

// Spielraum für Deckel-Passung
LID_TOL = 0.3;

// ════════════════════════════════════════════════════════════════════
//  FRONTPLATTE  (jetzt Teil des Unterteils)
// ════════════════════════════════════════════════════════════════════

// Display: Waveshare 3,5" IPS – sichtbare Fläche 73×43 mm
DISP_W = 73;
DISP_H = 43;
DISP_X = 5;
DISP_Y = (H - DISP_H) / 2;
DISP_OFFSET = 6;   // Display sitzt 6 mm hinter der Front (für Backlight-Träger)

// Rotary Encoder
ENC_D = 7;
ENC_X = W - 18;
ENC_Y = H / 2;
ENC_OFFSET = 8;

// 4 Tasten zwischen Display und Encoder
BTN_D  = 6;
BTN_X  = DISP_X + DISP_W + 10;
BTN_Y0 = H/2 + 12;
BTN_DY = 8;
BUTTONS = [
    [BTN_X, BTN_Y0          ],
    [BTN_X, BTN_Y0 - BTN_DY ],
    [BTN_X, BTN_Y0 - 2*BTN_DY],
    [BTN_X, BTN_Y0 - 3*BTN_DY],
];

// Lautsprecher-Schlitze
SPK_X     = DISP_X;
SPK_Y     = 4;
SPK_W     = DISP_W;
SPK_H     = 4;
SPK_SLOTS = 12;

// 3,5mm Klinke
JACK_D = 7;
JACK_X = W - 10;
JACK_Y = 6;

// ════════════════════════════════════════════════════════════════════
//  RÜCKSEITE
// ════════════════════════════════════════════════════════════════════

SMA_X      = 18;
SMA_Y_R    = H / 2;
USBC_X     = 50;
USBC_W     = 10;
USBC_H     = 5;
USB_DATA_X = 75;
USB_DATA_W = 14;
USB_DATA_H = 7;

VENT_W   = 2;
VENT_GAP = 3.5;
VENT_N   = 18;
VENT_H   = 14;

// ════════════════════════════════════════════════════════════════════
//  RPI ZERO 2 W
// ════════════════════════════════════════════════════════════════════

ZERO_X       = 15;
ZERO_Y       = 15;
ZERO_HOLE_DX = 58;
ZERO_HOLE_DY = 23;
HOLE_D       = 2.6;
INSERT_D     = 3.8;
INSERT_H     = 4;
BOSS_H       = 5;

// SDR-Halter
SDR_X = ZERO_X + 70;
SDR_Y = 15;
SDR_W = 60;
SDR_D = 28;

// ════════════════════════════════════════════════════════════════════
//  DECKEL-BEFESTIGUNG  (4× M2.5 Schrauben in Ecken)
// ════════════════════════════════════════════════════════════════════

SCREW_INSET = 6;          // Abstand der Schraube von der Außenkante
SCREW_HOLE_D = 2.7;       // Durchgangsbohrung im Deckel
SCREW_HEAD_D = 5;         // Senkkopf-Durchmesser
SCREW_HEAD_H = 1.5;       // Senkkopf-Tiefe
SCREW_BOSS_OD = 6.5;      // Außendurchmesser Bosss-Säulen im Unterteil

// 4 Eckpositionen
SCREW_POS = [
    [SCREW_INSET,        SCREW_INSET       ],
    [W - SCREW_INSET,    SCREW_INSET       ],
    [SCREW_INSET,        D - SCREW_INSET   ],
    [W - SCREW_INSET,    D - SCREW_INSET   ],
];

// ════════════════════════════════════════════════════════════════════
//  HILFSMODULE
// ════════════════════════════════════════════════════════════════════

module rbox(w, d, h, r, wall) {
    difference() {
        hull() {
            for (x=[r, w-r]) for (y=[r, d-r])
                translate([x, y, 0]) cylinder(r=r, h=h, $fn=32);
        }
        translate([wall, wall, wall])
        hull() {
            for (x=[r, w-2*wall-r]) for (y=[r, d-2*wall-r])
                translate([x, y, 0]) cylinder(r=max(0.5, r-wall*0.7), h=h, $fn=32);
        }
    }
}

module boss(od=BOSS_OD_DEFAULT, ih=BOSS_H) {
    difference() {
        cylinder(d=od, h=ih + INSERT_H, $fn=24);
        translate([0,0,ih])   cylinder(d=INSERT_D, h=INSERT_H+0.1, $fn=20);
        translate([0,0,-0.1]) cylinder(d=HOLE_D,   h=ih+0.2,       $fn=20);
    }
}
BOSS_OD_DEFAULT = 6.5;
