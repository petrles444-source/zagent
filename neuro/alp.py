# ============================================================
# main.py — Scientific pipeline for Russian char-level LM
# Reproducible · Multi-architecture · Statistical model selection
# ============================================================

# ---------- 1. IMPORTS ----------
import os, sys, math, json, time, random, hashlib, argparse, statistics
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Tuple, Callable, Optional, Any

import torch
import torch.nn as nn
import torch.nn.functional as F

torch.set_num_threads(max(1, os.cpu_count() or 1))


# ---------- 2. REPRODUCIBILITY ----------
def set_seed(seed: int) -> None:
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(False)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------- 3. CONFIG ----------
@dataclass
class Config:
    data_path: str = "data.txt"
    save_dir: str = "runs"
    block_size: int = 128
    batch_size: int = 64
    grad_clip: float = 1.0
    weight_decay: float = 1e-4
    val_ratio: float = 0.10
    test_ratio: float = 0.10
    seeds: Tuple[int, ...] = (42, 1337, 2024)
    eval_batches: int = 32
    patience: int = 5
    min_delta: float = 1e-4
    device: str = "cpu"


# ---------- 4. DATA ----------
BUILTIN = """
жили-были дед да баба. была у них курочка ряба.
снесла курочка яичко, не простое — золотое.
дед бил, бил — не разбил. баба била, била — не разбила.
мышка бежала, хвостиком махнула, яичко упало и разбилось.
посадил дед репку. выросла репка большая-пребольшая.
тянут-потянут — вытянули репку!
колобок, колобок, я тебя съем! — не ешь меня, заяц.
в лесу родилась ёлочка, в лесу она росла.
съешь же ещё этих мягких французских булок, да выпей чаю.
русский алфавит состоит из тридцати трёх букв.
нейросеть — это математическая модель. она учится на примерах.
утро было тихое и ясное. солнце медленно поднималось над лесом.
книга лежала на столе, раскрытая на середине.
программирование — это искусство объяснять компьютеру, что нужно сделать.
однажды маленький котёнок забрался на дерево и не смог слезть.
море было спокойным. волны тихо накатывали на песок.
математика — это язык, на котором написана вселенная.
зимой в городе особенно красиво. снег ложится на крыши.
весной всё просыпается. тает снег, бегут ручьи, поют птицы.
""".strip()


def load_corpus(path: str) -> str:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return BUILTIN


def normalize(text: str, lower: bool = True, yo_to_e: bool = True) -> str:
    import unicodedata
    text = unicodedata.normalize("NFC", text)
    text = text if not lower else text.lower()
    text = text.replace("ё", "е") if yo_to_e else text
    text = "\n".join(line.strip() for line in text.splitlines())
    text = "\n".join(line for line in text.splitlines() if line)
    return text


def build_vocab(text: str) -> Tuple[List[str], Dict[str, int], Dict[int, str]]:
    chars = sorted(set(text))
    stoi = {c: i for i, c in enumerate(chars)}
    itos = {i: c for c, i in stoi.items()}
    return chars, stoi, itos


def encode(text: str, stoi: Dict[str, int]) -> torch.Tensor:
    return torch.tensor([stoi[c] for c in text], dtype=torch.long)


def split_data(data: torch.Tensor, val_ratio: float, test_ratio: float) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    n = len(data)
    n_test = int(n * test_ratio)
    n_val = int(n * val_ratio)
    n_train = n - n_val - n_test
    return data[:n_train], data[n_train:n_train + n_val], data[n_train + n_val:]


def get_batch(data: torch.Tensor, block: int, batch: int, generator: Optional[torch.Generator] = None) -> Tuple[torch.Tensor, torch.Tensor]:
    ix = torch.randint(0, len(data) - block - 1, (batch,), generator=generator)
    x = torch.stack([data[i:i + block] for i in ix])
    y = torch.stack([data[i + 1:i + block + 1] for i in ix])
    return x, y


# ---------- 5. MODELS ----------
class Bigram(nn.Module):
    def __init__(self, V, **kw):
        super().__init__()
        self.t = nn.Embedding(V, V)
        nn.init.zeros_(self.t.weight)

    def forward(self, x, h=None):
        return self.t(x), None


class MLP(nn.Module):
    def __init__(self, V, emb_dim=64, hidden_dim=256, context=8, dropout=0.1, **kw):
        super().__init__()
        self.ctx = context
        self.emb = nn.Embedding(V, emb_dim)
        self.net = nn.Sequential(
            nn.Linear(emb_dim * context, hidden_dim), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(hidden_dim, V),
        )

    def forward(self, x, h=None):
        B, T = x.shape
        if T < self.ctx:
            pad = torch.zeros(B, self.ctx - T, dtype=x.dtype, device=x.device)
            x = torch.cat([pad, x], 1); T = self.ctx
        e = self.emb(x)
        outs = []
        for t in range(T):
            s = max(0, t - self.ctx + 1)
            c = e[:, s:t + 1]
            if c.size(1) < self.ctx:
                c = torch.cat([torch.zeros(B, self.ctx - c.size(1), e.size(-1), device=e.device), c], 1)
            outs.append(self.net(c.reshape(B, -1)))
        return torch.stack(outs, 1), None


class GRU(nn.Module):
    def __init__(self, V, emb_dim=96, hidden_dim=384, num_layers=1, dropout=0.1, **kw):
        super().__init__()
        self.emb = nn.Embedding(V, emb_dim)
        self.rnn = nn.GRU(emb_dim, hidden_dim, num_layers, batch_first=True,
                          dropout=dropout if num_layers > 1 else 0.0)
        self.drop = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_dim, V)

    def forward(self, x, h=None):
        o, h = self.rnn(self.emb(x), h)
        return self.fc(self.drop(o)), h


class LSTM(nn.Module):
    def __init__(self, V, emb_dim=96, hidden_dim=384, num_layers=1, dropout=0.1, **kw):
        super().__init__()
        self.emb = nn.Embedding(V, emb_dim)
        self.rnn = nn.LSTM(emb_dim, hidden_dim, num_layers, batch_first=True,
                           dropout=dropout if num_layers > 1 else 0.0)
        self.drop = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_dim, V)

    def forward(self, x, h=None):
        o, h = self.rnn(self.emb(x), h)
        return self.fc(self.drop(o)), h


class Attn(nn.Module):
    def __init__(self, d, nh, dp, bs):
        super().__init__()
        self.nh, self.hd = nh, d // nh
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.proj = nn.Linear(d, d, bias=False)
        self.dp = nn.Dropout(dp)
        self.register_buffer("mask", torch.tril(torch.ones(bs, bs)).view(1, 1, bs, bs), persistent=False)

    def forward(self, x):
        B, T, C = x.shape
        q, k, v = self.qkv(x).chunk(3, -1)
        q = q.view(B, T, self.nh, self.hd).transpose(1, 2)
        k = k.view(B, T, self.nh, self.hd).transpose(1, 2)
        v = v.view(B, T, self.nh, self.hd).transpose(1, 2)
        a = (q @ k.transpose(-2, -1)) / math.sqrt(self.hd)
        a = a.masked_fill(self.mask[:, :, :T, :T] == 0, float("-inf"))
        a = self.dp(F.softmax(a, -1))
        return self.proj((a @ v).transpose(1, 2).contiguous().view(B, T, C))


class Block(nn.Module):
    def __init__(self, d, nh, dp, bs):
        super().__init__()
        self.ln1, self.ln2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.attn = Attn(d, nh, dp, bs)
        self.mlp = nn.Sequential(nn.Linear(d, 4 * d), nn.GELU(), nn.Linear(4 * d, d), nn.Dropout(dp))

    def forward(self, x):
        x = x + self.attn(self.ln1(x))
        x = x + self.mlp(self.ln2(x))
        return x


class Transformer(nn.Module):
    def __init__(self, V, emb_dim=128, n_head=4, num_layers=3, dropout=0.1, block_size=128, **kw):
        super().__init__()
        self.bs = block_size
        self.tok = nn.Embedding(V, emb_dim)
        self.pos = nn.Embedding(block_size, emb_dim)
        self.drop = nn.Dropout(dropout)
        self.blocks = nn.ModuleList([Block(emb_dim, n_head, dropout, block_size) for _ in range(num_layers)])
        self.ln_f = nn.LayerNorm(emb_dim)
        self.head = nn.Linear(emb_dim, V, bias=False)
        self.head.weight = self.tok.weight
        self.apply(self._init)

    def _init(self, m):
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, 0.0, 0.02)
            if m.bias is not None: nn.init.zeros_(m.bias)
        elif isinstance(m, nn.Embedding):
            nn.init.normal_(m.weight, 0.0, 0.02)

    def forward(self, x, h=None):
        B, T = x.shape
        p = torch.arange(T, device=x.device).unsqueeze(0)
        z = self.drop(self.tok(x) + self.pos(p))
        for b in self.blocks: z = b(z)
        return self.head(self.ln_f(z)), None


REGISTRY: Dict[str, Callable] = {
    "bigram": Bigram, "mlp": MLP, "gru": GRU, "lstm": LSTM, "transformer": Transformer,
}


# ---------- 6. CANDIDATES ----------
@dataclass
class Candidate:
    name: str
    arch: str
    kwargs: Dict[str, Any] = field(default_factory=dict)
    lr: float = 3e-3
    batch_size: int = 64
    block_size: int = 128
    max_steps: int = 800
    eval_every: int = 100


def default_candidates() -> List[Candidate]:
    return [
        Candidate("bigram",       "bigram",      {},                                                       lr=1e-2,  batch_size=128, block_size=64,  max_steps=200),
        Candidate("mlp-c4",       "mlp",         dict(emb_dim=48, hidden_dim=192, context=4, dropout=0.0), lr=3e-3,  batch_size=64,  block_size=64,  max_steps=400),
        Candidate("mlp-c8",       "mlp",         dict(emb_dim=64, hidden_dim=256, context=8, dropout=0.0), lr=2e-3,  batch_size=64,  block_size=64,  max_steps=400),
        Candidate("gru-s",        "gru",         dict(emb_dim=64, hidden_dim=192, num_layers=1, dropout=0.0), lr=4e-3, batch_size=64, block_size=96, max_steps=600),
        Candidate("gru-m",        "gru",         dict(emb_dim=96, hidden_dim=384, num_layers=1, dropout=0.1), lr=3e-3, batch_size=64, block_size=96, max_steps=800),
        Candidate("gru-2l",       "gru",         dict(emb_dim=96, hidden_dim=320, num_layers=2, dropout=0.15), lr=3e-3, batch_size=64, block_size=96, max_steps=800),
        Candidate("lstm-m",       "lstm",        dict(emb_dim=96, hidden_dim=384, num_layers=1, dropout=0.1), lr=3e-3, batch_size=64, block_size=96, max_steps=800),
        Candidate("tf-tiny",      "transformer", dict(emb_dim=96, n_head=4, num_layers=2, dropout=0.1, block_size=96), lr=2e-3, batch_size=48, block_size=96, max_steps=800),
        Candidate("tf-small",     "transformer", dict(emb_dim=128, n_head=4, num_layers=3, dropout=0.1, block_size=96), lr=1.5e-3, batch_size=32, block_size=96, max_steps=800),
    ]


# ---------- 7. TRAINING ----------
@dataclass
class TrialResult:
    name: str
    arch: str
    seed: int
    best_val: float
    best_step: int
    train_loss: float
    val_loss: float
    ppl: float
    seconds: float
    params: int
    stopped_early: bool
    history: List[Tuple[int, float, float]]


@torch.no_grad()
def evaluate(model: nn.Module, data: torch.Tensor, block: int, batch: int, V: int, n_batches: int, gen: torch.Generator) -> float:
    model.eval()
    tot = 0.0
    for _ in range(n_batches):
        x, y = get_batch(data, block, batch, gen)
        logits, _ = model(x)
        tot += F.cross_entropy(logits.view(-1, V), y.view(-1)).item()
    return tot / n_batches


def train_trial(cand: Candidate, train: torch.Tensor, val: torch.Tensor, V: int, seed: int, cfg: Config) -> Tuple[TrialResult, nn.Module]:
    set_seed(seed)
    model = REGISTRY[cand.arch](V, **cand.kwargs)
    n_params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=cand.lr, weight_decay=cfg.weight_decay)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=cand.max_steps, eta_min=cand.lr * 0.1)
    gen = torch.Generator().manual_seed(seed)

    best_val, best_state, best_step, wait, stopped = float("inf"), None, 0, 0, False
    running, history = 0.0, []
    t0 = time.time()

    for step in range(1, cand.max_steps + 1):
        model.train()
        x, y = get_batch(train, cand.block_size, cand.batch_size, gen)
        opt.zero_grad()
        logits, _ = model(x)
        loss = F.cross_entropy(logits.view(-1, V), y.view(-1))
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
        opt.step()
        sch.step()
        running += loss.item()

        if step % cand.eval_every == 0:
            vl = evaluate(model, val, cand.block_size, cand.batch_size, V, cfg.eval_batches, gen)
            tr = running / cand.eval_every
            running = 0.0
            history.append((step, tr, vl))

            if vl < best_val - cfg.min_delta:
                best_val, best_step, wait = vl, step, 0
                best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            else:
                wait += 1
                if wait >= cfg.patience:
                    stopped = True
                    break

    if best_state is not None:
        model.load_state_dict(best_state)

    return TrialResult(
        name=cand.name, arch=cand.arch, seed=seed,
        best_val=best_val, best_step=best_step,
        train_loss=history[-1][1] if history else float("inf"),
        val_loss=best_val, ppl=math.exp(best_val),
        seconds=time.time() - t0, params=n_params,
        stopped_early=stopped, history=history,
    ), model


# ---------- 8. STATISTICS ----------
def mean_ci(xs: List[float], conf: float = 0.95) -> Tuple[float, float, float]:
    n = len(xs)
    if n < 2:
        return (xs[0] if xs else float("nan"), float("nan"), float("nan"))
    m = statistics.mean(xs)
    sd = statistics.stdev(xs)
    se = sd / math.sqrt(n)
    z = 1.96 if conf == 0.95 else 2.576
    return m, m - z * se, m + z * se


def paired_t(xs: List[float], ys: List[float]) -> Tuple[float, float]:
    if len(xs) != len(ys) or len(xs) < 2:
        return float("nan"), float("nan")
    d = [a - b for a, b in zip(xs, ys)]
    md = statistics.mean(d)
    sd = statistics.stdev(d)
    if sd == 0:
        return float("inf") if md != 0 else 0.0, 0.0 if md != 0 else 1.0
    t = md / (sd / math.sqrt(len(d)))
    df = len(d) - 1
    return t, df


def aggregate_trials(results: List[TrialResult]) -> Dict[str, Dict[str, Any]]:
    by_name: Dict[str, List[TrialResult]] = {}
    for r in results:
        by_name.setdefault(r.name, []).append(r)

    agg: Dict[str, Dict[str, Any]] = {}
    for name, trials in by_name.items():
        vals = [t.val_loss for t in trials]
        m, lo, hi = mean_ci(vals)
        agg[name] = {
            "arch": trials[0].arch,
            "n_seeds": len(trials),
            "mean_val": m,
            "ci_low": lo,
            "ci_high": hi,
            "std_val": statistics.stdev(vals) if len(vals) > 1 else 0.0,
            "mean_ppl": math.exp(m),
            "mean_sec": statistics.mean(t.seconds for t in trials),
            "params": trials[0].params,
            "seeds": [t.seed for t in trials],
            "vals": vals,
        }
    return agg


# ---------- 9. MODEL SELECTION ----------
def select_best(agg: Dict[str, Dict[str, Any]], top_k: int = 3) -> List[str]:
    return [n for n, _ in sorted(agg.items(), key=lambda kv: kv[1]["mean_val"])[:top_k]]


def confidence_rank(agg: Dict[str, Dict[str, Any]]) -> List[Tuple[str, float, float, float]]:
    rows = []
    for n, s in agg.items():
        rows.append((n, s["mean_val"], s["ci_low"], s["ci_high"]))
    return sorted(rows, key=lambda r: r[1])


# ---------- 10. FINAL TEST ----------
@torch.no_grad()
def final_test(model: nn.Module, test: torch.Tensor, block: int, batch: int, V: int, n_batches: int = 64) -> Tuple[float, float, float]:
    gen = torch.Generator().manual_seed(0)
    model.eval()
    tot, n = 0.0, 0
    correct, total = 0, 0
    for _ in range(n_batches):
        x, y = get_batch(test, block, batch, gen)
        logits, _ = model(x)
        tot += F.cross_entropy(logits.view(-1, V), y.view(-1)).item()
        n += 1
        pred = logits.argmax(-1)
        correct += (pred == y).sum().item()
        total += y.numel()
    return tot / n, math.exp(tot / n), correct / total


# ---------- 11. GENERATION ----------
@torch.no_grad()
def generate(model: nn.Module, stoi: Dict[str, int], itos: Dict[int, str],
             prompt: str, max_new: int = 200, temp: float = 0.8,
             top_k: int = 10, block: int = 128) -> str:
    model.eval()
    ids = [stoi.get(c, 0) for c in (prompt or " ")]
    x = torch.tensor(ids, dtype=torch.long).unsqueeze(0)
    out = list(ids)
    for _ in range(max_new):
        logits, _ = model(x[:, -block:])
        logits = logits[:, -1, :] / temp
        if top_k:
            v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
            logits[logits < v[:, [-1]]] = -float("inf")
        nxt = torch.multinomial(F.softmax(logits, -1), 1).item()
        out.append(nxt)
        x = torch.cat([x, torch.tensor([[nxt]])], 1)
    return "".join(itos[i] for i in out)


# ---------- 12. PERSISTENCE ----------
def save_artifact(path: str, model: nn.Module, cand: Candidate, V: int,
                  stoi, itos, metrics: Dict[str, float]) -> None:
    torch.save({
        "state": model.state_dict(),
        "arch": cand.arch,
        "kwargs": cand.kwargs,
        "block_size": cand.block_size,
        "vocab_size": V,
        "stoi": stoi, "itos": itos,
        "metrics": metrics,
    }, path)


def save_report(path: str, agg: Dict[str, Any], results: List[TrialResult],
                winner: str, test_metrics: Dict[str, float]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "aggregate": agg,
            "trials": [asdict(r) for r in results],
            "winner": winner,
            "test": test_metrics,
        }, f, ensure_ascii=False, indent=2, default=str)


# ---------- 13. MAIN ----------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=str, default="data.txt")
    p.add_argument("--out", type=str, default="runs")
    p.add_argument("--steps", type=int, default=None)
    p.add_argument("--seeds", type=int, nargs="+", default=[42, 1337, 2024])
    p.add_argument("--budget", type=int, default=None)
    p.add_argument("--top-k", type=int, default=3)
    p.add_argument("--quick", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = Config(data_path=args.data, save_dir=args.out, seeds=tuple(args.seeds))
    os.makedirs(cfg.save_dir, exist_ok=True)
    set_seed(cfg.seeds[0])

    print("=" * 100)
    print("  SCIENTIFIC MODEL SELECTION · Russian char-level LM · CPU")
    print("=" * 100)
    print(f"threads={torch.get_num_threads()} · device={cfg.device} · seeds={cfg.seeds}")

    # 1. Data
    text = normalize(load_corpus(cfg.data_path))
    chars, stoi, itos = build_vocab(text)
    V = len(chars)
    data = encode(text, stoi)
    train, val, test = split_data(data, cfg.val_ratio, cfg.test_ratio)
    print(f"corpus={len(text):,} · vocab={V} · train={len(train):,} · val={len(val):,} · test={len(test):,}")
    print(f"sha256={sha256(text)}")

    # 2. Candidates
    candidates = default_candidates()
    if args.quick:
        keep = {"bigram", "mlp-c8", "gru-m", "tf-tiny"}
        candidates = [c for c in candidates if c.name in keep]
    if args.steps is not None:
        for c in candidates:
            c.max_steps = args.steps
    print(f"candidates={len(candidates)} · seeds_per_candidate={len(cfg.seeds)}")

    # 3. Trials
    print("-" * 100)
    results: List[TrialResult] = []
    trained: Dict[Tuple[str, int], nn.Module] = {}
    t_start = time.time()

    for ci, cand in enumerate(candidates, 1):
        if args.budget and (time.time() - t_start) > args.budget:
            print(f"[budget] stop at candidate {ci}")
            break
        for seed in cfg.seeds:
            print(f"[{ci}/{len(candidates)}] {cand.name:<10} seed={seed:<5}", end=" ", flush=True)
            r, m = train_trial(cand, train, val, V, seed, cfg)
            results.append(r)
            trained[(cand.name, seed)] = m
            print(f"val={r.val_loss:.4f} ppl={r.ppl:.2f} step={r.best_step} "
                  f"{r.seconds:.1f}s early={r.stopped_early}")

    # 4. Aggregation
    agg = aggregate_trials(results)
    ranked = confidence_rank(agg)

    print()
    print("=" * 100)
    print(f"{'rank':<5}{'model':<12}{'arch':<13}{'params':>9}"
          f"{'mean_val':>12}{'95% CI':>22}{'std':>9}{'ppl':>9}{'sec':>8}")
    print("-" * 100)
    for i, (name, m, lo, hi) in enumerate(ranked, 1):
        s = agg[name]
        ci = f"[{lo:.4f}, {hi:.4f}]"
        print(f"{i:<5}{name:<12}{s['arch']:<13}{s['params']:>9,}"
              f"{m:>12.4f}{ci:>22}{s['std_val']:>9.4f}{s['mean_ppl']:>9.2f}{s['mean_sec']:>8.1f}")
    print("=" * 100)

    # 5. Winner
    top = select_best(agg, top_k=args.top_k)
    winner = top[0]
    print(f"winner={winner} · arch={agg[winner]['arch']} · "
          f"mean_val={agg[winner]['mean_val']:.4f} · "
          f"CI=[{agg[winner]['ci_low']:.4f}, {agg[winner]['ci_high']:.4f}]")

    # 6. Paired t-test vs runner-up
    if len(top) >= 2:
        a, b = top[0], top[1]
        t, df = paired_t(agg[a]["vals"], agg[b]["vals"])
        print(f"paired_t({a} vs {b}) = {t:.3f} · df={df}")

    # 7. Retrain winner on train+val, evaluate on test
    print("-" * 100)
    print(f"retraining winner={winner} on train+val, testing on held-out test")
    best_cand = next(c for c in candidates if c.name == winner)
    best_cand.max_steps = int(best_cand.max_steps * 1.15)
    train_val = torch.cat([train, val])
    _, final_model = train_trial(best_cand, train_val, test, V, cfg.seeds[0], cfg)
    test_loss, test_ppl, test_acc = final_test(final_model, test, best_cand.block_size, best_cand.batch_size, V)
    print(f"test_loss={test_loss:.4f} · test_ppl={test_ppl:.2f} · test_acc={test_acc:.4f}")

    # 8. Save
    save_artifact(os.path.join(cfg.save_dir, "best_model.pt"),
                  final_model, best_cand, V, stoi, itos,
                  {"val_loss": agg[winner]["mean_val"],
                   "test_loss": test_loss, "test_ppl": test_ppl, "test_acc": test_acc})
    save_report(os.path.join(cfg.save_dir, "search_report.json"),
                agg, results, winner,
                {"test_loss": test_loss, "test_ppl": test_ppl, "test_acc": test_acc})
    print(f"saved: {cfg.save_dir}/best_model.pt · {cfg.save_dir}/search_report.json")

    # 9. Sample
    print("=" * 100)
    print("SAMPLE")
    print("=" * 100)
    for prompt in ["жили-были", "в лесу", "нейросеть"]:
        out = generate(final_model, stoi, itos, prompt, max_new=180,
                       temp=0.8, top_k=10, block=best_cand.block_size)
        print(f"▶ {prompt!r}\n{out}\n")

    # 10. Summary
    print("=" * 100)
    print(f"total_time={time.time() - t_start:.1f}s · "
          f"trials={len(results)} · candidates={len(candidates)} · "
          f"winner={winner} · test_ppl={test_ppl:.2f}")
    print("=" * 100)


if __name__ == "__main__":
    main()