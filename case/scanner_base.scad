// scanner_base.scad — Gehäuse-Unterteil MIT integrierter Frontplatte
//
// Druck: Auf den Boden gelegt, ohne Stützen druckbar
//        (Frontplatte hat 12° Überhang am Display-Ausschnitt = unkritisch).
//        Falls Probleme mit Tasten-Bohrungen: minimale Stützen für die
//        ersten 2 mm der Front-Innenseite reichen.

include <case_params.scad>

// ════════════════════════════════════════════════════════════════════
//  FRONTPLATTE — als Subtraktions-Modul (sitzt auf y = 0)
// ════════════════════════════════════════════════════════════════════

FRONT_THICKNESS = T;   // Wandstärke der Front (entspricht Gehäusewand)

module front_cutouts() {
    // Alle Durchbrüche in der Frontplatte (y = 0 bis y = T)

    // Display – durchgängig
    translate([DISP_X, -0.1, DISP_Y])
        cube([DISP_W, FRONT_THICKNESS + 0.2, DISP_H]);

    // Display-Schraublöcher M2 (4 Ecken außerhalb des Sichtfelds)
    for (dx=[DISP_X - 3, DISP_X + DISP_W + 3])
        for (dy=[DISP_Y + 4, DISP_Y + DISP_H - 4])
            translate([dx, FRONT_THICKNESS, dy])
                rotate([90,0,0])
                cylinder(d=2.2, h=FRONT_THICKNESS+0.2, $fn=16);

    // Rotary Encoder – Achsen-Durchbruch
    translate([ENC_X, -0.1, ENC_Y])
        rotate([-90,0,0])
        cylinder(d=ENC_D, h=FRONT_THICKNESS+0.2, $fn=30);

    // 4 Taster-Bohrungen
    for (b=BUTTONS)
        translate([b[0], -0.1, b[1]])
            rotate([-90,0,0])
            cylinder(d=BTN_D, h=FRONT_THICKNESS+0.2, $fn=20);

    // Lautsprecher-Schlitze
    for (i=[0:SPK_SLOTS-1])
        translate([SPK_X + i*(SPK_W/SPK_SLOTS) + 0.5, -0.1, SPK_Y])
            cube([SPK_W/SPK_SLOTS - 1.5, FRONT_THICKNESS+0.2, SPK_H]);

    // 3,5mm Klinke
    translate([JACK_X, -0.1, JACK_Y])
        rotate([-90,0,0])
        cylinder(d=JACK_D, h=FRONT_THICKNESS+0.2, $fn=20);
}

// ════════════════════════════════════════════════════════════════════
//  RÜCKSEITE — Subtraktions-Modul
// ════════════════════════════════════════════════════════════════════

module rear_cutouts() {
    // SMA-Antenne mit Mutter-Versenkung
    translate([SMA_X, D-T-0.1, SMA_Y_R])
        rotate([-90,0,0]) cylinder(d=7, h=T+0.2, $fn=24);
    translate([SMA_X, D-1, SMA_Y_R])
        rotate([-90,0,0]) cylinder(d=10, h=1.2, $fn=24);

    // USB-C
    translate([USBC_X, D-T-0.1, H/2 - USBC_H/2])
        cube([USBC_W, T+0.2, USBC_H]);

    // USB-A
    translate([USB_DATA_X, D-T-0.1, H/2 - USB_DATA_H/2])
        cube([USB_DATA_W, T+0.2, USB_DATA_H]);

    // Belüftungsschlitze
    for (i=[0:VENT_N-1])
        translate([15 + i*(VENT_W+VENT_GAP), D-T-0.1, SZ-VENT_H-4])
            cube([VENT_W, T+0.2, VENT_H]);
}

// ════════════════════════════════════════════════════════════════════
//  INNERE STRUKTUREN
// ════════════════════════════════════════════════════════════════════

module internal_features() {
    // RPi Zero 2 W Befestigungsbossen
    translate([ZERO_X, ZERO_Y, T])
        for (dx=[0, ZERO_HOLE_DX]) for (dy=[0, ZERO_HOLE_DY])
            translate([dx, dy, 0]) boss();

    // SDR-Halter (zwei kleine Stege)
    translate([SDR_X-2,      SDR_Y, T]) cube([3, SDR_D, 10]);
    translate([SDR_X+SDR_W-1, SDR_Y, T]) cube([3, SDR_D, 10]);

    // Display-Träger hinter der Frontplatte (zwei seitliche Stege)
    translate([DISP_X - 4, T, DISP_Y - 3])
        cube([3, DISP_OFFSET, DISP_H + 6]);
    translate([DISP_X + DISP_W + 1, T, DISP_Y - 3])
        cube([3, DISP_OFFSET, DISP_H + 6]);

    // Schrauben-Bossen für Deckel (4 Ecken, vollhöhe Unterteil)
    for (p=SCREW_POS)
        translate([p[0], p[1], 0])
            difference() {
                cylinder(d=SCREW_BOSS_OD, h=SZ, $fn=24);
                translate([0,0,SZ-INSERT_H])
                    cylinder(d=INSERT_D, h=INSERT_H+0.1, $fn=20);
            }
}

// ════════════════════════════════════════════════════════════════════
//  HAUPTKÖRPER UNTERTEIL
// ════════════════════════════════════════════════════════════════════

module scanner_base() {
    difference() {
        union() {
            // Außenwand (geschlossen oben)
            intersection() {
                rbox(W, D, SZ + T, R, T);
                cube([W, D, SZ + T]);
            }
            internal_features();
        }

        front_cutouts();
        rear_cutouts();

        // Belüftung Boden
        for (i=[0:5]) for (j=[0:8])
            translate([ZERO_X + 70 + i*8, 50 + j*10, -0.1])
                cylinder(d=2.5, h=T+0.2, $fn=12);

        // Innere obere Stirnfläche frei machen
        translate([T, T, SZ + 0.1])
            cube([W - 2*T, D - 2*T, T + 0.1]);
    }
}

// ════════════════════════════════════════════════════════════════════
//  RENDER
// ════════════════════════════════════════════════════════════════════

scanner_base();
