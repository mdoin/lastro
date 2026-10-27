"""Equipe do Lastro: registro de agentes, roteamento e auditoria determinística.

Módulo puro (sem rede, sem banco): usado tanto pelo web app (orquestrador) quanto pelo worker do mentor
(runtime dos agentes), para que os dois lados concordem sobre quem existe e o que cada um pode fazer.
"""
