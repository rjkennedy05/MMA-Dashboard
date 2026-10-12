import assert from "node:assert/strict";
import {registerHooks} from "node:module";
import test from "node:test";
import {createClient} from "@supabase/supabase-js";

// Exercise real SDK query builders and HTTP contracts without credentials/network.
const calls=[];
let tables={};
const client=createClient("https://example.invalid","offline-placeholder",{auth:{persistSession:false,autoRefreshToken:false},global:{fetch:async(url,options={})=>{
  const target=new URL(url);const body=options.body?JSON.parse(options.body):null;
  calls.push({target,body,method:options.method});
  if(target.pathname.includes("/rpc/"))return new Response(JSON.stringify({ticket_id:42}),{status:200,headers:{"Content-Type":"application/json"}});
  const table=target.pathname.split("/").at(-1);
  let rows=tables[table]??[];
  for(const [key,value] of target.searchParams){
    if(value.startsWith("gt."))rows=rows.filter(row=>Number(row[key])>Number(value.slice(3)));
    if(value==="is.null")rows=rows.filter(row=>row[key]==null);
  }
  return new Response(JSON.stringify(rows.slice(0,2)),{status:200,headers:{"Content-Type":"application/json"}});
}}});
globalThis.__mmaTestClient=client;
registerHooks({
  resolve(specifier,context,next){
    if(specifier.startsWith(".")&&!/\.[a-z]+$/i.test(specifier))return next(specifier+".js",context);
    return next(specifier,context);
  },
  load(url,context,next){
    if(url.endsWith("/src/lib/supabase.js"))return {format:"module",source:"export const supabase=globalThis.__mmaTestClient;",shortCircuit:true};
    return next(url,context);
  },
});
const {readRows}=await import("./readRows.js");
const results=await import("./resultsService.js");

test("real SDK pagination reads past server caps and does not retain older sort predicates",async()=>{
  tables={fights:[1,2,3,4,5].map(fight_id=>({fight_id}))};calls.length=0;
  const query=client.from("fights").select("fight_id").order("fight_order");
  const rows=await readRows(()=>query,"fight_id");
  assert.deepEqual(rows.map(r=>r.fight_id),[1,2,3,4,5]);
  assert.equal(calls.length,4);assert.ok(calls.every(c=>c.target.searchParams.get("order")==="fight_id.asc"));
  assert.equal(query.url.searchParams.get("order"),"fight_order.asc");
});
test("saving a single uses one atomic request and creates a retry identity",async()=>{
  calls.length=0;await results.saveSingleBet({fightId:5,betSide:"fighter_a",sportsbook:"DraftKings",betPrice:110,stakeUnits:1});
  assert.equal(calls.length,1);assert.match(calls[0].target.pathname,/mma_save_ticket$/);
  assert.equal(calls[0].body.p_ticket.ticket_type,"single");assert.ok(calls[0].body.p_ticket.request_id);
  assert.deepEqual(calls[0].body.p_legs,[{fight_id:5,bet_side:"fighter_a",leg_price:110}]);
});
test("parlay edits save every leg with the expected ticket revision in one request",async()=>{
  calls.length=0;
  await results.updateTrackedBet({bet_id:"ticket:42",ticket_id:42,ticket_type:"parlay",revision:3,
    legs:[{leg_id:1,fight_id:5},{leg_id:2,fight_id:6}]},
    {bet_sportsbook:"DraftKings",bet_price:300,stake_units:1,legs:[{leg_id:1,bet_side:"fighter_a",leg_price:110},{leg_id:2,bet_side:"fighter_b",leg_price:120}]});
  assert.equal(calls.length,1);assert.equal(calls[0].body.p_revision,3);
  assert.deepEqual(calls[0].body.p_legs.map(l=>l.fight_id),[5,6]);
});
test("archiving the current period is a single database transaction",async()=>{
  calls.length=0;await results.resetCurrentBetPeriod();assert.equal(calls.length,1);
  assert.match(calls[0].target.pathname,/mma_archive_bet_period$/);
});
test("new ticket singles and legacy singles remain readable together",async()=>{
  const fight={fight_id:5,event_id:1,fighter_a:{fighter_id:11,full_name:"A"},fighter_b:{fighter_id:12,full_name:"B"},
    events:{event_id:1,event_name:"Card",event_date:"2026-10-12",promotions:{name:"UFC"}}};
  tables={fight_research:[{fight_id:5,bet_side:"fighter_a",stake_units:1,bet_price:110,fights: fight}],
    bet_tickets:[{ticket_id:42,revision:1,ticket_type:"single",ticket_price:120,stake_units:1,
      bet_legs:[{leg_id:1,fight_id:5,bet_side:"fighter_b",leg_price:120,leg_order:1,fights:fight}]}]};
  const bets=await results.getTrackedBets();assert.equal(bets.length,2);
  assert.ok(bets.some(b=>b.bet_id==="ticket:42"&&b.selection_name==="B"));
  assert.ok(bets.some(b=>b.bet_id==="single:5"&&b.selection_name==="A"));
});
