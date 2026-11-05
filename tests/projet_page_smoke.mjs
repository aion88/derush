import fs from "fs";
const html = fs.readFileSync("derush/projet.html", "utf8");
const js = html.match(/<script>([\s\S]*)<\/script>/)[1];
const log = [], calls = [];
const mk = (name = "el") => new Proxy(function () {}, {
  get(t, k) {
    if (k === Symbol.toPrimitive) return () => "";
    if (k === "classList") return { add() {}, remove() {}, toggle() {}, contains() { return false; } };
    if (k === "style" || k === "dataset") return {};
    if (k === "getBoundingClientRect") return () => ({ left: 0 });
    if (k === "clientWidth") return 900;
    if (k === "paused") return true;
    if (k === "scrollLeft") return 0;
    if (k === "options") return { length: 1 };
    if (k === "querySelectorAll") return () => [];
    if (k === "closest") return () => null;
    if (k === "then") return undefined;
    return mk(String(k));
  },
  apply() { return mk(); },
  set(t, k, val) { if (k === "textContent") log.push(String(val)); return true; },
});
// Fumée de projet.html hors navigateur : un DOM de façade, le vrai script, de vraies opérations de piste.
// Ce que ça NE couvre PAS : le rendu réel, le glisser à la souris, la lecture. Lancé par tests/test_studio.sh.
let DATA = JSON.parse(process.argv[2]);
globalThis.document = { querySelector: () => mk(), createElement: () => mk(), addEventListener() {}, activeElement: null };
globalThis.window = { addEventListener() {} };
globalThis.location = { search: "?p=x" };
globalThis.requestAnimationFrame = () => 0;
globalThis.fetch = async (u, o) => {
  calls.push([String(u), o && o.body]);
  const body = o && o.body ? JSON.parse(o.body) : null;
  if (String(u).startsWith("/projet/op")) { DATA = { ...DATA, sequence: DATA.sequence.slice(1), _op: body }; }
  return { json: async () => (String(u).startsWith("/projet/") ? DATA : []) };
};
const f = new Function(js + "\n;return {render, draw, couperIci, op, retirerChoisi, bougerBord, get HEAD(){return HEAD}, set HEAD(v){HEAD=v}, set SEL(v){SEL=v}, get DATA(){return DATA}, etape, jouerDe, lirePiste, WIDf:()=>WID};");
const api = f();
const pause = ms => new Promise(r => setTimeout(r, ms));
const ops = () => calls.filter(c => c[0].startsWith("/projet/op")).map(c => c[1]);
await pause(50);
const out = { status: log.slice(-1)[0], widths: api.WIDf().map(Math.round) };
api.HEAD = 2.0; api.SEL = 0; api.couperIci(); await pause(20);
out.cut = ops().slice(-1)[0];
api.SEL = 0; api.bougerBord(1); await pause(20);
out.trim = ops().slice(-1)[0];
api.SEL = 0; api.retirerChoisi(); await pause(20);
out.del = ops().slice(-1)[0];
console.log(JSON.stringify(out));
