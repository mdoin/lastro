"""Demonstração em terminal com dados 100% sintéticos: diagnóstico + três projeções.

Uso: uv run python scripts/demo.py [persona_id] [aporte_mensal] [meses] [--projecao]

A projeção só aparece quando o próximo passo do diagnóstico é investir. Nas
outras etapas, `--projecao` mostra uma projeção hipotética, marcada como tal.
"""
import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from financial_engine.budget import Debt, FinancialSnapshot, free_cash_flow, monthly_guidance  # noqa: E402
from financial_engine.money import format_brl, format_pct  # noqa: E402
from financial_engine.projection import Assumptions, Plan, compare_scenarios  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures_synthetic"
INVESTING_STAGE = "investir_para_metas"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("persona", nargs="?", default="iniciante-150")
    parser.add_argument("aporte", nargs="?", help="aporte mensal da projeção; padrão: sobra mensal estimada")
    parser.add_argument("meses", nargs="?", type=int, default=120)
    parser.add_argument("--projecao", action="store_true", help="mostrar a projeção mesmo quando o passo atual não é investir")
    args = parser.parse_args()

    personas = json.loads((FIXTURES / "personas.json").read_text(encoding="utf-8"))
    p = next(x for x in personas["personas"] if x["id"] == args.persona)
    snapshot = FinancialSnapshot(
        p["net_monthly_income"], p["essential_expenses"], p["variable_expenses"], p["liquid_reserve"],
        p["available_this_month"], tuple(Debt(**d) for d in p["debts"]), as_of=personas["as_of"],
    )
    g = monthly_guidance(snapshot, reserve_target_months=6, reference_annual_return=Decimal("0.10"))

    print(f"== DADOS SINTÉTICOS · {p['label']} · referência {personas['as_of']} ==\n")
    print("Situação:"); [print("  -", s) for s in g.situation]
    print(f"\nPróximo passo [{g.stage}]: {g.next_step}")
    if g.allocation:
        print("\nCenário para o valor disponível:")
        for line in g.allocation:
            print(f"  {format_brl(line.amount):>12}  {str(line.percent).replace('.', ',')+'%':>7}  {line.purpose} — {line.rationale}")
    for c in g.comparisons:
        print("  ·", c)
    print("\nPremissas:"); [print("  -", s) for s in g.premises]
    print("\nAntes de decidir, confira:"); [print("  [ ]", q) for q in g.checklist]
    print(f"\nAcompanhamento: {g.follow_up}")
    print(f"Aviso: {g.disclaimer}")

    if g.stage != INVESTING_STAGE and not args.projecao:
        print(f"\n== Projeção omitida: o próximo passo é '{g.stage}', não investir. "
              "Use --projecao para ver uma projeção hipotética. ==")
        return

    fcf = free_cash_flow(snapshot)
    contribution = Decimal(args.aporte) if args.aporte is not None else max(fcf, Decimal(0))
    scen = json.loads((FIXTURES / "scenarios.json").read_text(encoding="utf-8"))
    plan = Plan(Decimal(p["liquid_reserve"]), contribution, args.meses)

    title = "Projeção HIPOTÉTICA (não é o passo recomendado agora)" if g.stage != INVESTING_STAGE else "Projeção"
    print(f"\n== {title}: aporte de {format_brl(plan.monthly_contribution)}/mês por {plan.months} meses ==")
    print(f"({scen['note']})")
    if contribution > fcf:
        print(f"  ATENÇÃO: o aporte de {format_brl(contribution)} passa da sobra mensal estimada "
              f"({format_brl(fcf)}); ele não cabe no orçamento informado.")
    if g.stage == "priorizar_divida":
        print("  ATENÇÃO: a projeção ignora as dívidas informadas e os juros que continuariam correndo.")
    for r in compare_scenarios(plan, [Assumptions(**s) for s in scen["scenarios"]]):
        a = r.assumptions
        print(f"\n  {r.scenario}: retorno {format_pct(a.annual_return)} · inflação {format_pct(a.annual_inflation)} · "
              f"taxa {format_pct(a.annual_fee)}")
        print(f"    nominal {format_brl(r.final_nominal)} | em dinheiro de hoje {format_brl(r.final_real)} | "
              f"aportado {format_brl(r.total_contributed)}")
        if r.final_real < plan.initial + r.total_contributed:
            print("    Neste cenário, o poder de compra final fica ABAIXO do total aportado.")
        print(f"    inputs_fingerprint {r.inputs_fingerprint}")
    print("\n  Tributos não modelados nesta versão; cenários não são previsão.")


if __name__ == "__main__":
    main()
