from webui import initialize
import modules.interrogate

initialize()
interrogator = modules.interrogate.InterrogateModels("interrogate")
interrogator.load()
interrogator.categories()
