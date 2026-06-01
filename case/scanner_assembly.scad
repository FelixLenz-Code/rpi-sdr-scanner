// scanner_assembly.scad — Vorschau-Datei
// Zeigt Unterteil + Deckel zusammen für die Visualisierung.
// NICHT zum Drucken – einzelne .scad-Dateien verwenden.

include <case_params.scad>

MODE = "exploded";   // "exploded" | "assembled"

LID_H = H - SZ;

module preview() {
    // Unterteil (importiert)
    color("DimGray", 0.9)
        import("scanner_base.stl");

    // Deckel (importiert)
    color("Gray", 0.7)
        translate([0, 0, SZ + (MODE == "exploded" ? 15 : 0)])
        import("scanner_lid.stl");
}

// Hinweis: Damit das funktioniert, vorher die STLs exportieren:
//   openscad -o scanner_base.stl scanner_base.scad
//   openscad -o scanner_lid.stl  scanner_lid.scad
//
// Alternativ: einfach die beiden Dateien in OpenSCAD nebeneinander öffnen.

preview();
