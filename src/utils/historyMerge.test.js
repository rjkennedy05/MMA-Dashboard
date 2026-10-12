import assert from "node:assert/strict";
import test from "node:test";
import {mergeFighterHistories} from "./historyMerge.js";

test("a recovered bout listed by two sources appears once, including spelling variants",()=>{
  const bout={date:"2026-10-10",opponent:{full_name:"José Silva"},fightId:1};
  assert.equal(mergeFighterHistories([], [bout,{...bout,fightId:2,opponent:{full_name:"JoseSilva"}}]).length,1);
});
test("official bouts retain their identity and a rematch or other sport remains separate",()=>{
  const bout={date:"2026-10-10",opponent:{full_name:"A Fighter"},fightId:1};
  const rows=mergeFighterHistories([bout],[{...bout,fightId:99},{...bout,date:"2026-10-11",fightId:2},{...bout,ruleset:"Kickboxing",fightId:3}]);
  assert.equal(rows.length,3);assert.ok(rows.some(r=>r.fightId===1));assert.ok(!rows.some(r=>r.fightId===99));
});
