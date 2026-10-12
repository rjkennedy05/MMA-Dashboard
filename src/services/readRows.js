/** Complete reads with stable keyset pagination, including server-capped pages. */
export async function readRows(queryFactory, key, size = 500) {
  const rows = [], seen = new Set();
  let last;
  for (let pageNumber = 0; pageNumber < 2000; pageNumber += 1) {
    const source=queryFactory();
    let query=Object.assign(Object.create(Object.getPrototypeOf(source)),source);
    query.url=new URL(source.url);
    query.url.searchParams.delete("order");
    query=query.order(key, { ascending: true }).limit(size);
    if (last !== undefined) query = query.gt(key, last);
    const { data, error } = await query;
    if (error) throw error;
    if (!data?.length) return rows;
    for (const row of data) {
      if (row[key] === undefined || seen.has(row[key])) throw new Error("Incomplete database page; refresh was stopped.");
      seen.add(row[key]); rows.push(row);
    }
    last = data.at(-1)[key];
  }
  throw new Error("Database read exceeded its page limit.");
}
