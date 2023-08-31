from webui import initialize
import modules.interrogate

initialize.initialize()
interrogator = modules.interrogate.InterrogateModels("interrogate")
interrogator.load()
interrogator.categories()
