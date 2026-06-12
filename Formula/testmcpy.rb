class Testmcpy < Formula
  include Language::Python::Virtualenv

  desc "MCP Testing Framework - Test LLM tool calling with MCP services"
  homepage "https://github.com/preset-io/testmcpy"
  url "https://files.pythonhosted.org/packages/source/t/testmcpy/testmcpy-0.10.3.tar.gz"
  sha256 "170dc2f6694e03385f3fd2da409329ed67fad00875af9335a8eca24ce533ecc6"
  license "Apache-2.0"

  depends_on "python@3.11"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "MCP Testing Framework", shell_output("#{bin}/testmcpy --help")
  end
end
