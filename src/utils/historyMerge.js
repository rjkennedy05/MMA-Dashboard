function name(value) {
  return String(value??"").normalize("NFKD").replace(/[\u0300-\u036f]/g,"").toLowerCase().replace(/[^a-z0-9]/g,"");
}
function signature(entry) {
  const opponent=name(entry.opponent?.full_name);
  return entry.date && opponent ? `${entry.date}|${opponent}|${name(entry.ruleset??"MMA")}` : `id:${entry.fightId}`;
}

/** Official identities take precedence; duplicate fallback sources add detail once. */
export function mergeFighterHistories(official=[],fallback=[]) {
  const rows=new Map();
  for(const entry of [...official,...fallback]) {
    const key=signature(entry);
    if(!rows.has(key)) rows.set(key,entry);
  }
  return [...rows.values()].sort((a,b)=>String(b.date??"").localeCompare(String(a.date??"")));
}
