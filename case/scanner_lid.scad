// scanner_lid.scad — Gehäuse-Deckel (nur Oberseite)
//
// Druck: Auf den Kopf gelegt drucken (Oberfläche zeigt nach unten = glatt).
//        OpenSCAD-PART unten dreht automatisch in Druckposition.
//
// Befestigung: 4× M2.5 Senkkopfschrauben in die Wärmeeinsätze im Unterteil.

include <case_params.scad>

PART = "print";   // "preview" = wie montiert | "print" = druckbereit auf Kopf

// ════════════════════════════════════════════════════════════════════
//  DECKEL
// ════════════════════════════════════════════════════════════════════

LID_H = H - SZ;   // Deckel-Höhe = Gesamthöhe minus Unterteil

module lid() {
    difference() {
        union() {
            // Deckelform (rundum-Rahmen + Oberseite)
            difference() {
                // Außenkontur
                hull() {
                    for (x=[R, W-R]) for (y=[R, D-R])
                        translate([x, y, 0]) cylinder(r=R, h=LID_H, $fn=32);
                }
                // Innenraum aushöhlen (lässt T mm Wand stehen)
                translate([T, T, -0.1])
                hull() {
                    for (x=[R, W-2*T-R]) for (y=[R, D-2*T-R])
                        translate([x, y, 0])
                            cylinder(r=max(0.5, R-T*0.7), h=LID_H - T, $fn=32);
                }
            }

            // Einlauf-Lippe: passt mit etwas Spiel in das Unterteil
            translate([T + LID_TOL, T + LID_TOL, 0])
                difference() {
                    // Lippe
                    hull() {
                        for (x=[R, W-2*T-2*LID_TOL-R]) for (y=[R, D-2*T-2*LID_TOL-R])
                            translate([x, y, 0])
                                cylinder(r=max(0.5, R-T*0.7), h=3, $fn=32);
                    }
                    // Innenraum auch hier raus
                    translate([1.2, 1.2, -0.1])
                    hull() {
                        for (x=[R, W-2*T-2*LID_TOL-2.4-R]) for (y=[R, D-2*T-2*LID_TOL-2.4-R])
                            translate([x, y, 0])
                                cylinder(r=max(0.5, R-T*0.7), h=3.2, $fn=32);
                    }
                }
        }

        // ── Schraublöcher mit Senkkopf ─────────────────────────────
        for (p=SCREW_POS) {
            translate([p[0], p[1], -0.1]) {
                // Durchgangsbohrung
                cylinder(d=SCREW_HOLE_D, h=LID_H + 0.2, $fn=20);
                // Senkkopf-Versenkung (Kegel)
                translate([0, 0, LID_H - SCREW_HEAD_H + 0.01])
                    cylinder(d1=SCREW_HOLE_D + 0.5,
                             d2=SCREW_HEAD_D,
                             h=SCREW_HEAD_H + 0.1, $fn=24);
            }
        }

        // ── Belüftungs-Schlitze Oberseite ──────────────────────────
        for (i=[0:14])
            translate([20 + i*10, D*0.55, LID_H - T - 0.1])
                cube([4, 25, T + 0.2]);

        // Optional: Mini-Logo-Aussparung (3D-druckbare Beschriftung)
        // translate([W/2 - 20, D/2, LID_H - 0.4])
        //     linear_extrude(0.5) text("SDR", size=8, halign="center");
    }
}

// ════════════════════════════════════════════════════════════════════
//  RENDER
// ════════════════════════════════════════════════════════════════════

if (PART == "print") {
    // Auf den Kopf zum Drucken (gute Oberfläche)
    translate([0, 0, LID_H]) rotate([180, 0, 0]) lid();
} else {
    // Wie montiert (oben auf dem Unterteil)
    translate([0, 0, SZ]) lid();
}
