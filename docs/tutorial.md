# 📘 Param Manager – Guia Completo de Uso

## 🟦 Uso Básico

Crie um arquivo `main.py`:

```python
from param_manager import ParamManager

# Obter a instância do gerenciador
param_manager = ParamManager()

# Recuperar todos os parâmetros de um app
params = param_manager.get_all_params('nome_do_app')

# Recuperar um parâmetro específico
param = param_manager.get_param('nome_do_app', 'nome_parametro')

# Limpar o cache para um app específico
param_manager.clear_cache('nome_do_app')

# Obter informações sobre o cache atual
cache_info = param_manager.get_cache_info()
print(cache_info)
```

---

## ⚙️ Configuração Avançada

```python
from param_manager import ParamManager

param_manager = ParamManager.get_instance(
    api_url="http://minha-api.exemplo.com",
    cache_duration=1800,
    timeout=10,
    username="admin",
    password="SenhaSegura123"
)
```

---

## 🔐 Autenticação Automática com Username e Password

O Param Manager aceita autenticação com `username` e `password`.

### ✔ Diretamente

```python
param_manager = ParamManager.get_instance(
    api_url="http://minha-api.exemplo.com",
    username="admin",
    password="senha123"
)
```

### ✔ Via `.env`

Crie o arquivo:

```
PARAM_MANAGER_USERNAME=admin
PARAM_MANAGER_PASSWORD=MinhaSenhaUltraSegura
```

E inicialize:

```python
param_manager = ParamManager.get_instance(
    api_url="http://minha-api.exemplo.com"
)
```

---

## 🟩 Criar ou Atualizar Parâmetros (`upsert_params`)

```python
param_manager.upsert_params(
    "financeiro",
    "limite_diario",
    value=5000,
    param_type="int",
    description="Limite diário permitido",
    user_editable=True,
    min_value=0,
    max_value=10000,
    referenced_params=["limite_global"]
)
```

---

## 🟥 Deletar Parâmetros

```python
param_manager.delete_param("financeiro", "limite_diario")
```

---

## 🟧 Atualizar Apenas um Campo

```python
param_manager.update_param(
    "financeiro",
    "limite_diario",
    value=7500
)
```

---

## 🟦 Obter Schema de um Parâmetro

```python
schema = param_manager.get_param_schema("financeiro", "limite_diario")
print(schema)
```

---

## 🧠 Fallback Quando API Está Indisponível

1. Tenta acessar a API  
2. Se falhar, usa dados locais (TinyDB)  
3. Continua funcionando normalmente  

---

## 📂 Armazenamento Local

O Param Manager salva fallback em:

```
param_manager/params_db.json
```

---

## 📌 Resumo dos Recursos

- Autenticação com usuário e senha ✔  
- Renovação automática de token ✔  
- Cache com TTL ✔  
- Fallback automático ✔  
- Upsert completo ✔  
- Update granular ✔  
- Deleção ✔  
- TinyDB ✔  
