const D = require('../../data.js');
const DISHES = D.DISHES, ING = D.ING, PRICES = D.PRICES || {}, REST = D.REST;
const byName = {};
DISHES.forEach(d => byName[d.name] = d);
const SHOP_NAMES = { hmart: 'H Mart', heb: 'HEB', costco: 'Costco' };
const CAT_ORDER = ['肉类', '海鲜', '蛋奶', '蔬菜', '豆制品', '主食', '干货'];
const WD = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
const EXCL_MAP = { '忌高胆固醇': '高胆固醇', '忌高饱和脂肪': '高饱和脂肪', '忌反式脂肪': '反式脂肪风险' };

const pad = n => (n < 10 ? '0' : '') + n;
const fmtDate = d => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
const now = new Date();
const TODAY = fmtDate(now);
const YESTER = fmtDate(new Date(now.getTime() - 864e5));
const IS_WEEKEND = now.getDay() === 0 || now.getDay() === 6;

const restPool = REST ? (REST.visited || []).concat(REST.wishlist || []) : [];
const restByName = {};
restPool.forEach(r => restByName[r.name] = r);

function get(k, dft) {
  try { const v = wx.getStorageSync(k); return v === '' ? dft : v; } catch (e) { return dft; }
}
const set = (k, v) => { try { wx.setStorageSync(k, v); } catch (e) {} };

Page({
  data: { mode: 'day', todayLabel: '', filtersOpen: false },

  state: null, day: null, week: null, hist: null, shops: null, bought: null,

  onLoad() {
    this.state = get('jld_filters', { cat: [], meat: [], spice: [], cui: [], excl: [], scope: ['含相册发现的菜'] });
    this.day = get('jld_day', null);
    if (this.day && (!this.day.date || !('m' in this.day))) this.day = null;
    this.week = get('jld_week', null);
    if (this.week && this.week.days && this.week.days[0] && !('m' in this.week.days[0])) this.week = null;
    this.hist = get('jld_hist', {});
    for (const k in this.hist) {
      if (this.hist[k] && 'dm' in this.hist[k]) this.hist[k] = { m: this.hist[k].dm, v: this.hist[k].ds };
    }
    this.bought = get('jld_bought', []);
    const avail = Object.keys(PRICES).filter(k => Object.keys(PRICES[k]).length);
    this.availShops = avail;
    this.shops = (get('jld_shops', []) || []).filter(s => avail.includes(s));
    if (!this.shops.length && avail.length) this.shops = [avail[0]];
    this.setData({
      mode: get('jld_mode', 'day'),
      todayLabel: (now.getMonth() + 1) + '月' + now.getDate() + '日 周' + '日一二三四五六'[now.getDay()],
    });
    this.renderAll();
  },

  // ---------- pools ----------
  matches(d, ignoreCui) {
    const s = this.state;
    if (s.cat.length && !d.cat.some(c => s.cat.includes(c))) return false;
    if (s.meat.length && !d.meat.some(m => s.meat.includes(m))) return false;
    if (s.spice.length && !s.spice.includes(d.spice === 0 ? '不辣' : '微辣')) return false;
    if (!ignoreCui && s.cui.length && d.meal !== '早饭' && !s.cui.includes(d.cui)) return false;
    if (s.excl.some(e => d.flags.includes(EXCL_MAP[e]))) return false;
    if (!s.scope.includes('含相册发现的菜') && d.src === 'album') return false;
    return true;
  },
  pool(meal) { return DISHES.filter(d => d.meal === meal && this.matches(d, meal === '早饭')); },
  draw(arr, used, avoid) {
    avoid = avoid || [];
    let c = arr.filter(d => !used.includes(d.name) && !avoid.includes(d.name));
    if (!c.length) c = arr.filter(d => !avoid.includes(d.name));
    if (!c.length) c = arr;
    if (!c.length) return null;
    const p = c[Math.floor(Math.random() * c.length)];
    used.push(p.name);
    return p.name;
  },
  pickRest(avoid) {
    const pool = restPool.filter(r => !(avoid || []).includes(r.name));
    if (!pool.length) return null;
    const pref = (REST && REST.pref) || {};
    const w = pool.map(r => (r.v ? 2 : 1) * (1 + 1.5 * (pref[r.cuisine] || 0)));
    let x = Math.random() * w.reduce((a, b) => a + b, 0);
    for (let i = 0; i < pool.length; i++) { x -= w[i]; if (x <= 0) return pool[i].name; }
    return pool[pool.length - 1].name;
  },

  // ---------- actions ----------
  onTab(e) {
    const m = e.currentTarget.dataset.m;
    set('jld_mode', m);
    this.setData({ mode: m });
    if (m === 'shop') this.renderShop();
  },
  onGo() {
    const used = [];
    this.day = {
      date: TODAY,
      b: this.draw(this.pool('早饭'), used),
      m: this.draw(this.pool('肉菜'), used),
      v: this.draw(this.pool('蔬菜'), used),
      s: this.draw(this.pool('汤'), used),
      r: IS_WEEKEND && restPool.length ? this.pickRest([]) : null,
    };
    this.saveDay(); this.renderDay();
  },
  saveDay() {
    set('jld_day', this.day);
    if (this.day) { this.hist[this.day.date] = { m: this.day.m, v: this.day.v }; this.pruneHist(); }
  },
  pruneHist() {
    const keys = Object.keys(this.hist).sort().slice(-14);
    const h = {}; keys.forEach(k => h[k] = this.hist[k]);
    this.hist = h; set('jld_hist', h);
  },
  onReroll(e) {
    if (!this.day) return;
    const SLOT_MEAL = { b: '早饭', m: '肉菜', v: '蔬菜', s: '汤' };
    const keys = e.currentTarget.dataset.k.split(',');
    for (const k of keys) {
      const others = ['b', 'm', 'v', 's'].filter(x => x !== k).map(x => this.day[x]).filter(Boolean);
      this.day[k] = this.draw(this.pool(SLOT_MEAL[k]), [], others.concat(this.day[k] ? [this.day[k]] : []));
    }
    this.saveDay(); this.renderDay();
  },
  onDayRestSwap() {
    if (!this.day) return;
    this.day.r = this.pickRest(this.day.r ? [this.day.r] : []);
    this.saveDay(); this.renderDay();
  },
  onGoWeek() {
    const uB = [], uM = [], uV = [], uS = [], uR = [];
    this.week = { days: WD.map((_, i) => ({
      b: this.draw(this.pool('早饭'), uB),
      m: this.draw(this.pool('肉菜'), uM),
      v: this.draw(this.pool('蔬菜'), uV),
      s: this.draw(this.pool('汤'), uS),
      r: (i >= 5 && restPool.length) ? (uR[uR.length] = this.pickRest(uR)) : null,
    })) };
    set('jld_week', this.week); this.renderWeek();
  },
  onWeekReroll(e) {
    const i = +e.currentTarget.dataset.i;
    const d = this.week.days[i];
    const others = key => this.week.days.flatMap((x, j) => j !== i ? [x[key]] : []).filter(Boolean);
    d.b = this.draw(this.pool('早饭'), [], others('b').concat(d.b ? [d.b] : []));
    d.m = this.draw(this.pool('肉菜'), [], others('m').concat(d.m ? [d.m] : []));
    d.v = this.draw(this.pool('蔬菜'), [], others('v').concat(d.v ? [d.v] : []));
    d.s = this.draw(this.pool('汤'), [], others('s').concat(d.s ? [d.s] : []));
    if (i >= 5 && restPool.length) d.r = this.pickRest(others('r').concat(d.r ? [d.r] : []));
    set('jld_week', this.week); this.renderWeek();
  },
  onWeekRestSwap(e) {
    const i = +e.currentTarget.dataset.i;
    const others = this.week.days.flatMap((x, j) => j !== i ? [x.r] : []).filter(Boolean);
    this.week.days[i].r = this.pickRest(others.concat(this.week.days[i].r ? [this.week.days[i].r] : []));
    set('jld_week', this.week); this.renderWeek();
  },
  onChip(e) {
    const { g, o } = e.currentTarget.dataset;
    const arr = this.state[g];
    const i = arr.indexOf(o);
    i >= 0 ? arr.splice(i, 1) : arr.push(o);
    set('jld_filters', this.state);
    this.renderAll();
  },
  onToggleFilters() { this.setData({ filtersOpen: !this.data.filtersOpen }); },
  onCard(e) {
    const d = byName[e.currentTarget.dataset.n];
    if (!d) return;
    this.setData({ veil: {
      name: d.name, img: d.img, chips: this.chipList(d),
      meta: d.meal + (d.src === 'album' ? '・相册里发现的菜' : '') +
        (d.count ? ('・相册里拍过 ' + d.count + ' 次') : '・相册里暂时没找到照片'),
    } });
  },
  onCloseVeil() { this.setData({ veil: null }); },
  onRestTap(e) {
    const name = e.currentTarget.dataset.n;
    wx.setClipboardData({ data: name, success: () => wx.showToast({ title: '店名已复制', icon: 'none' }) });
  },

  // ---------- shop ----------
  onShopChip(e) {
    const s = e.currentTarget.dataset.s;
    const i = this.shops.indexOf(s);
    i >= 0 ? this.shops.splice(i, 1) : this.shops.push(s);
    set('jld_shops', this.shops);
    this.renderShop();
  },
  onGrocRow(e) {
    const k = e.currentTarget.dataset.i;
    const i = this.bought.indexOf(k);
    i >= 0 ? this.bought.splice(i, 1) : this.bought.push(k);
    set('jld_bought', this.bought);
    this.renderShop();
  },
  onClearBought() { this.bought = []; set('jld_bought', []); this.renderShop(); },
  onCopyList() {
    const g = this.grocery();
    if (!g.src) return;
    const lines = ['家里的菜 采购清单 ' + TODAY, g.src, ''];
    for (const grp of g.groups) {
      lines.push('【' + grp.cat + '】');
      for (const r of grp.rows) {
        const ps = r.prices.filter(p => !p.nop).map(p => p.shop + ' ' + p.price).join(' / ');
        lines.push('[' + (r.bought ? 'x' : ' ') + '] ' + r.item + ' ' + r.qty + (ps ? ' — ' + ps : ''));
      }
      lines.push('');
    }
    if (g.pantry.length) lines.push('【常备调味清点】', g.pantry.join('、'));
    wx.setClipboardData({ data: lines.join('\n'), success: () => wx.showToast({ title: '清单已复制', icon: 'none' }) });
  },

  // ---------- render models ----------
  chipList(d) {
    const out = d.cat.map(c => ({ t: c, cls: c === '纤维' ? 'jade' : '' }));
    if (d.spice > 0) out.push({ t: '微辣', cls: 'spice' });
    if (d.meal !== '早饭') out.push({ t: d.cui, cls: '' });
    d.flags.forEach(f => out.push({ t: '⚠' + (f === '反式脂肪风险' ? '反式脂肪' : f), cls: 'warn' }));
    if (d.src === 'album') out.push({ t: '相册', cls: 'jade' });
    return out;
  },
  slot(name) {
    const d = byName[name];
    return d ? { name: d.name, img: d.img, chips: this.chipList(d) } : null;
  },
  restModel(name) {
    const r = restByName[name];
    if (!r) return null;
    return {
      name: r.name, cuisine: r.cuisine,
      tag: r.v ? ('去过' + (r.rating != null ? '⭐' + r.rating : '')) : '想去',
      km: r.km != null ? r.km + 'km' : '', fast: !!r.fast,
    };
  },
  renderDay() {
    let v = null;
    if (this.day) {
      const y = this.hist[YESTER];
      v = {
        b: this.slot(this.day.b),
        lunch: (y && (y.m || y.v)) ? [this.slot(y.m), this.slot(y.v)].filter(Boolean) : null,
        m: this.slot(this.day.m), v: this.slot(this.day.v), s: this.slot(this.day.s),
        rest: IS_WEEKEND && this.day.r ? this.restModel(this.day.r) : null,
      };
    }
    this.setData({ dayView: v });
  },
  renderWeek() {
    let v = null;
    if (this.week) {
      v = this.week.days.map((d, i) => ({
        wd: WD[i], i,
        b: this.slot(d.b),
        lunch: i === 0 ? null : [this.slot(this.week.days[i - 1].m), this.slot(this.week.days[i - 1].v)].filter(Boolean),
        m: this.slot(d.m), v: this.slot(d.v), s: this.slot(d.s),
        rest: i >= 5 && d.r ? this.restModel(d.r) : null,
      }));
    }
    this.setData({ weekView: v });
  },
  renderFilters() {
    const GROUPS = {
      cat: ['蛋白', '碳水', '纤维'],
      meat: ['鸡', '猪', '牛', '羊', '鸭', '鱼虾', '蛋', '豆制品'],
      spice: ['不辣', '微辣'],
      cui: [...new Set(DISHES.filter(d => d.meal !== '早饭').map(d => d.cui))],
      excl: ['忌高胆固醇', '忌高饱和脂肪', '忌反式脂肪'],
      scope: ['含相册发现的菜'],
    };
    const LABELS = { cat: '营养', meat: '食材', spice: '辣度', cui: '菜系（只筛正餐）', excl: '忌口', scope: '范围' };
    const groups = Object.keys(GROUPS).map(g => ({
      g, label: LABELS[g],
      chips: GROUPS[g].map(o => ({ o, on: this.state[g].includes(o) })),
    }));
    const on = Object.values(this.state).reduce((s, v) => s + v.length, 0) - this.state.scope.length;
    this.setData({ filterGroups: groups, fhint: on > 0 ? '已选 ' + on + ' 项' : '不限' });
  },
  renderGrid() {
    const sections = ['早饭', '肉菜', '蔬菜', '小菜', '点心', '汤'].map(meal => {
      const all = DISHES.filter(d => d.meal === meal);
      const ok = all.filter(d => this.matches(d, meal === '早饭'));
      return { meal, cnt: ok.length + ' / ' + all.length + ' 道',
        cards: all.map(d => ({ name: d.name, img: d.img, chips: this.chipList(d), dim: !ok.includes(d) })) };
    });
    this.setData({ sections });
  },
  grocery() {
    let src = null, names = [];
    if (this.week) {
      src = '按「这周」计划（带饭为前晚剩菜，不重复计）';
      this.week.days.forEach(d => [d.b, d.m, d.v, d.s].forEach(n => n && names.push(n)));
    } else if (this.day) {
      src = '按「今天」菜单（先生成整周计划可得一周清单）';
      names = [this.day.b, this.day.m, this.day.v, this.day.s].filter(Boolean);
    }
    const map = {}, pantry = [];
    for (const n of names) {
      for (const i of ING[n] || []) {
        if (i.pantry) { if (!pantry.includes(i.item)) pantry.push(i.item); continue; }
        const e = map[i.item] = map[i.item] || { item: i.item, en: i.en, category: i.category, qtys: [], n: 0 };
        e.qtys.push(i.qty); e.n++;
      }
    }
    let total = 0, priced = 0, count = 0;
    const groups = [];
    for (const cat of CAT_ORDER) {
      const rows = Object.values(map).filter(r => r.category === cat).map(r => {
        count++;
        const uniq = [...new Set(r.qtys)];
        const qty = uniq.length === 1 ? (r.n > 1 ? uniq[0] + ' ×' + r.n : uniq[0]) : r.qtys.join('、');
        const prices = this.shops.map(s => {
          const hit = PRICES[s] && PRICES[s][r.en];
          return { shop: SHOP_NAMES[s] || s, price: hit ? hit.price : '无报价', nop: !hit };
        });
        const nums = prices.filter(p => !p.nop).map(p => parseFloat(p.price.replace('$', '')));
        if (nums.length) { total += Math.min.apply(null, nums); priced++; }
        return { item: r.item, qty, prices, bought: this.bought.includes(r.item) };
      });
      if (rows.length) groups.push({ cat, rows });
    }
    const sameday = this.shops.some(s => PRICES[s] && Object.values(PRICES[s]).some(v => v.src === 'sameday'));
    return { src, groups, pantry, total: total.toFixed(2), priced, count, sameday };
  },
  renderShop() {
    const g = this.grocery();
    this.setData({ shopView: {
      src: g.src, groups: g.groups, pantry: g.pantry.join('・'), pantryCnt: g.pantry.length,
      total: g.total, priced: g.priced, count: g.count, sameday: g.sameday,
      shops: this.availShops.map(s => ({ s, label: SHOP_NAMES[s] || s, on: this.shops.includes(s) })),
    } });
  },
  renderAll() { this.renderDay(); this.renderWeek(); this.renderFilters(); this.renderGrid(); if (this.data.mode === 'shop') this.renderShop(); },
});
